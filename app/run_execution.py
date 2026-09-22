"""一次本地执行的应用编排，由 RunService 创建持久 Run 后调用。

调用前必须已提交产品 Run 的创建或审批响应。此模块仅启动本地执行，不创建 Run，
也不把本地执行结果直接作为数据库状态。
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from langchain_core.messages import HumanMessage
from langgraph.types import Command
from shikigen.callback_handler import TokenTracker
from shikigen.execution import ExecutionOutcome, ExecutionRegistry, RunExecution
from shikigen.loop import execute_agent_loop
from shikigen.stream import MessageData, UsageData

from app.run_events import RunEventIngestor
from app.run_state import CommittedEvent, CommittedRunState

logger = logging.getLogger(__name__)


class RunSettlement(Protocol):
  async def settle_execution(
    self,
    *,
    thread_id: str,
    run_id: str,
    outcome: ExecutionOutcome,
    invocation_seq: int | None = None,
    usage: UsageData | None = None,
  ) -> CommittedRunState:
    """事务提交状态和生命周期事实后返回。

    必须检查允许的旧状态；迟到完成不能覆盖已提交取消。
    失败须抛出异常，不能返回未经提交的候选状态。
    ChatStore.settle_execution 提供事务实现。
    """
    ...


def start_run_execution(
  *,
  agent,
  message: HumanMessage | Command,
  checkpoint: dict | None = None,
  thread_id: str,
  run_id: str,
  registry: ExecutionRegistry,
  settlement: RunSettlement,
  initial_events: tuple[CommittedEvent, ...] = (),
  ingest_delta: Callable[[MessageData], Awaitable[None]] | None = None,
  ingest_message: Callable[[dict[str, Any]], Awaitable[int]] | None = None,
) -> RunExecution:
  """为已持久创建的 Run 启动一次执行；不依赖 HTTP 消费者回收资源。"""
  execution = RunExecution(
    run_id=run_id,
    thread_id=thread_id,
    replay_start_seq=min((event["seq"] for event in initial_events), default=0),
  )
  registry.install(execution)

  async def execute() -> None:
    tracker = TokenTracker()
    try:
      RunEventIngestor.publish(execution.stream, initial_events)
      outcome = await execute_agent_loop(
        agent,
        message,
        execution=execution,
        checkpoint=checkpoint,
        token_tracker=tracker,
        # 这里传入了 ingest_delta 和 ingest_message 回调，用于处理增量消息和完整消息。
        # todo. 后续看看是不是可以穿一个 adapter 来统一处理增量和完整消息。
        ingest_delta=ingest_delta,
        ingest_message=ingest_message,
      )
      async with execution.settlement_lock:
        try:
          # todo. 中断是在这里面写入数据库的，看看怎么搬到 stream 里面
          # 看能不能在 consume_event_stream 里面处理
          committed = await settlement.settle_execution(
            thread_id=thread_id,
            run_id=run_id,
            outcome=outcome,
            usage=tracker.summary(),
            invocation_seq=next(
              (
                e["seq"]
                for e in reversed(initial_events)
                if e["event_type"] == "run_running"
              ),
              None,
            ),
          )
        except Exception:
          RunEventIngestor.notify_failure(execution.stream, "run_persistence_failed")
          raise

        if committed.usage is not None:
          execution.stream.publish("usage", committed.usage)
        RunEventIngestor.publish(
          execution.stream, committed.events, settlement=committed
        )
    except asyncio.CancelledError:
      # shutdown／外部 Task 取消不是用户的持久取消操作。
      RunEventIngestor.notify_failure(execution.stream, "execution_stopped")
      raise
    finally:
      async with execution.settlement_lock:
        execution.stream.close()
        registry.remove(execution)

  def on_done(task: asyncio.Task[None]) -> None:
    # Task 可能在协程第一次执行之前被取消；此时内部 finally 不会运行。
    execution.stream.close()
    registry.remove(execution)
    if not task.cancelled() and (error := task.exception()) is not None:
      logger.error(
        "Product execution failed: thread_id=%s run_id=%s",
        thread_id,
        run_id,
        exc_info=(type(error), error, error.__traceback__),
      )

  coroutine = execute()
  try:
    task = asyncio.create_task(coroutine, name=f"run:{run_id}")
  except BaseException:
    coroutine.close()
    execution.stream.close()
    registry.remove(execution)
    raise
  execution.retain(task)
  task.add_done_callback(on_done)
  return execution
