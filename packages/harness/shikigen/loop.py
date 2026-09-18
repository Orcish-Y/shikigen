from __future__ import annotations

import asyncio
from collections.abc import AsyncIterable
from typing import TYPE_CHECKING, Protocol

from langchain_core.language_models.chat_model_stream import AsyncChatModelStream
from langchain_core.messages import HumanMessage
from pydantic import BaseModel

from shikigen.execution import (
  ExecutionOutcome,
  ExecutionPause,
  ExecutionReason,
  RunExecution,
)
from shikigen.runtime_context import AgentRunContext
from shikigen.stream import MessageData, ToolCallData

if TYPE_CHECKING:
  from shikigen.callback_handler import TokenTracker
  from shikigen.run_manager import RunRecord


class ToolCallStream(Protocol):
  tool_name: str
  input: object
  output: object

  @property
  def output_deltas(self) -> AsyncIterable[object]: ...


class AgentEventStream(Protocol):
  """Loop 消费的 v3 投影；上游通过 setattr 动态挂载，未提供静态属性声明。"""

  messages: AsyncIterable[AsyncChatModelStream]
  tool_calls: AsyncIterable[ToolCallStream]


async def execute_agent_loop(
  agent,  # 编译好的 agent graph
  new_message: HumanMessage,
  *,
  execution: RunExecution,
  token_tracker: TokenTracker | None = None,
) -> ExecutionOutcome:
  """使用新消息执行 agent，由 checkpointer 恢复此前的完整状态。

  并发消费 messages（token 流）和 tool_calls（工具调用）。
  返回执行结果，不发布产品终态、不关闭 Stream；外部 Task 取消继续传播。
  使用 checkpoint 的 Graph 在调用退出后检查暂停；审批策略由应用负责。
  """

  if execution.abort_event.is_set():
    return ExecutionOutcome(ExecutionReason.ABORTED)

  async def handle_messages(event_stream: AgentEventStream) -> None:
    async for message in event_stream.messages:
      emitted_text = False
      async for text_delta in message.text:
        if getattr(message, "namespace", []):
          continue
        emitted_text = True
        data: MessageData = {"text": text_delta, "done": False}
        if identity := getattr(message, "message_id", None):
          data["message_id"] = identity
        execution.stream.publish("message", data)
      if emitted_text:
        end: MessageData = {"text": "", "done": True}
        if identity := getattr(message, "message_id", None):
          end["message_id"] = identity
        execution.stream.publish("message", end)

  async def handle_tool_calls(event_stream: AgentEventStream) -> None:
    async for call in event_stream.tool_calls:
      # 消费完增量后，call.output 才是完整的工具输出。
      async for _ in call.output_deltas:
        pass

      if getattr(call, "namespace", []):
        continue
      data: ToolCallData = {
        "name": call.tool_name,
        "input": call.input,
        "output": (
          call.output.model_dump(mode="json")
          if isinstance(call.output, BaseModel)
          else call.output
        ),
      }
      if identity := getattr(call, "tool_call_id", None):
        data["tool_call_id"] = identity
        data["message_id"] = f"tool-result:{identity}"
      execution.stream.publish("tool_call", data)

  async def consume_event_stream(event_stream: AgentEventStream) -> None:
    async with asyncio.TaskGroup() as group:
      group.create_task(handle_messages(event_stream))
      group.create_task(handle_tool_calls(event_stream))

  async def wait_for_stream_outcome(event_stream: AgentEventStream) -> ExecutionReason:
    """等待流消费完成或取消信号，并在返回前回收两个等待任务。"""
    consume_task = asyncio.create_task(consume_event_stream(event_stream))
    abort_task = asyncio.create_task(execution.abort_event.wait())

    try:
      done, _ = await asyncio.wait(
        {consume_task, abort_task},
        return_when=asyncio.FIRST_COMPLETED,
      )

      if consume_task in done:
        await consume_task
        return ExecutionReason.COMPLETED
      return ExecutionReason.ABORTED
    finally:
      for task in (consume_task, abort_task):
        if not task.done():
          task.cancel()
      await asyncio.gather(consume_task, abort_task, return_exceptions=True)

  config: dict = {"configurable": {"thread_id": execution.thread_id}}

  # 将 token_tracker 挂到 LangChain callback 链上
  if token_tracker is not None:
    config.setdefault("callbacks", []).append(token_tracker)

  try:
    async with await agent.astream_events(
      {"messages": [new_message]},
      config=config,
      context=AgentRunContext(
        thread_id=execution.thread_id,
        run_id=execution.run_id,
      ),
      version="v3",
    ) as event_stream:
      execution.stream.publish("metadata", {"run_id": execution.run_id})
      outcome = await wait_for_stream_outcome(event_stream)

    if outcome is ExecutionReason.COMPLETED and getattr(agent, "checkpointer", None):
      snapshot = await agent.aget_state(config, subgraphs=True)
      if snapshot.next or snapshot.interrupts:
        return ExecutionOutcome(
          ExecutionReason.INTERRUPTED,
          pause=ExecutionPause(
            checkpoint=snapshot.config,
            interrupts=tuple(
              {"id": item.id, "value": item.value} for item in snapshot.interrupts
            ),
          ),
        )

    if outcome is ExecutionReason.COMPLETED and token_tracker is not None:
      # usage 必须在 terminal event 之前发布。
      execution.stream.publish("usage", token_tracker.summary())
  except Exception as error:
    return ExecutionOutcome(ExecutionReason.FAILED, error=error)
  else:
    return ExecutionOutcome(outcome)


async def run_agent_loop(
  agent,
  new_message: HumanMessage,
  *,
  record: RunRecord,
  token_tracker: TokenTracker | None = None,
) -> None:
  """旧应用兼容入口；第 4 步切换后删除，禁止新产品编排使用。

  保留旧调用方的内存状态和终态事件语义；它不代表状态拆分已经完成。
  """
  from shikigen.run_manager import RunStatus

  record.start()
  try:
    outcome = await execute_agent_loop(
      agent,
      new_message,
      execution=RunExecution(
        run_id=record.run_id,
        thread_id=record.thread_id,
        stream=record.stream,
        abort_event=record.abort_event,
      ),
      token_tracker=token_tracker,
    )
  except asyncio.CancelledError:
    record.finish(RunStatus.CANCELLED)
    raise
  if outcome.reason is ExecutionReason.FAILED:
    assert outcome.error is not None
    record.finish(RunStatus.ERROR, error=outcome.error)
    raise outcome.error
  record.finish(
    RunStatus.COMPLETED
    if outcome.reason is ExecutionReason.COMPLETED
    else RunStatus.CANCELLED
  )
