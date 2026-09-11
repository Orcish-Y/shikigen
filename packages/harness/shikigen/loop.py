from __future__ import annotations

import asyncio
from collections.abc import AsyncIterable
from typing import TYPE_CHECKING, Protocol

from langchain_core.language_models.chat_model_stream import AsyncChatModelStream
from langchain_core.messages import HumanMessage

from shikigen.run_manager import RunRecord, RunStatus
from shikigen.runtime_context import AgentRunContext

if TYPE_CHECKING:
  from shikigen.callback_handler import TokenTracker


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


async def run_agent_loop(
  agent,  # 编译好的 agent graph
  new_message: HumanMessage,
  *,
  record: RunRecord,
  token_tracker: TokenTracker | None = None,
) -> None:
  """使用新消息执行 agent，由 checkpointer 恢复此前的完整状态。

  对应用 deer-flow 的 _stream_once()。
  并发消费 messages（token 流）和 tool_calls（工具调用）。
  """

  async def handle_messages(event_stream: AgentEventStream) -> None:
    async for message in event_stream.messages:
      emitted_text = False
      async for text_delta in message.text:
        emitted_text = True
        record.stream.publish("message", {"text": text_delta, "done": False})
      if emitted_text:
        record.stream.publish("message", {"text": "", "done": True})

  async def handle_tool_calls(event_stream: AgentEventStream) -> None:
    async for call in event_stream.tool_calls:
      # 消费完增量后，call.output 才是完整的工具输出。
      async for _ in call.output_deltas:
        pass

      record.stream.publish(
        "tool_call",
        {
          "name": call.tool_name,
          "input": call.input,
          "output": call.output,
        },
      )

  async def consume_event_stream(event_stream: AgentEventStream) -> None:
    async with asyncio.TaskGroup() as group:
      group.create_task(handle_messages(event_stream))
      group.create_task(handle_tool_calls(event_stream))

  async def wait_for_stream_outcome(event_stream: AgentEventStream) -> RunStatus:
    """等待流消费完成或取消信号，并在返回前回收两个等待任务。"""
    consume_task = asyncio.create_task(consume_event_stream(event_stream))
    abort_task = asyncio.create_task(record.abort_event.wait())

    try:
      done, _ = await asyncio.wait(
        {consume_task, abort_task},
        return_when=asyncio.FIRST_COMPLETED,
      )

      if consume_task in done:
        await consume_task
        return RunStatus.COMPLETED
      return RunStatus.CANCELLED
    finally:
      for task in (consume_task, abort_task):
        if not task.done():
          task.cancel()
      await asyncio.gather(consume_task, abort_task, return_exceptions=True)

  config: dict = {"configurable": {"thread_id": record.thread_id}}

  # 将 token_tracker 挂到 LangChain callback 链上
  if token_tracker is not None:
    config.setdefault("callbacks", []).append(token_tracker)

  record.start()
  try:
    async with await agent.astream_events(
      {"messages": [new_message]},
      config=config,
      context=AgentRunContext(
        thread_id=record.thread_id,
        run_id=record.run_id,
      ),
      version="v3",
    ) as event_stream:
      record.stream.publish("metadata", {"run_id": record.run_id})
      outcome = await wait_for_stream_outcome(event_stream)

    if outcome is RunStatus.COMPLETED and token_tracker is not None:
      # usage 必须在 terminal event 之前发布。
      record.stream.publish("usage", token_tracker.summary())
  except asyncio.CancelledError:
    record.finish(RunStatus.CANCELLED)
    raise
  except Exception as error:
    record.finish(RunStatus.ERROR, error=error)
    raise
  else:
    record.finish(outcome)
