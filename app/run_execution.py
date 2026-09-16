"""一次本地执行的应用编排，由 RunService 创建持久 Run 后调用。

调用前必须已提交产品 Run 的创建。此模块仅启动本地执行，不创建 Run，
也不把本地执行结果直接作为数据库状态。
"""

import asyncio
import logging
from typing import Protocol

from langchain_core.messages import HumanMessage
from shikigen.callback_handler import TokenTracker
from shikigen.execution import ExecutionOutcome, ExecutionRegistry, RunExecution
from shikigen.loop import execute_agent_loop

from app.run_events import RunEventIngestor
from app.run_state import CommittedEvent, CommittedRunState

logger = logging.getLogger(__name__)


class RunSettlement(Protocol):
  async def settle_execution(
    self, *, thread_id: str, run_id: str, outcome: ExecutionOutcome
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
  message: HumanMessage,
  thread_id: str,
  run_id: str,
  registry: ExecutionRegistry,
  settlement: RunSettlement,
  initial_events: tuple[CommittedEvent, ...] = (),
) -> RunExecution:
  """为已持久创建的 Run 启动一次执行；不依赖 HTTP 消费者回收资源。"""
  execution = RunExecution(run_id=run_id, thread_id=thread_id)
  registry.install(execution)

  async def execute() -> None:
    try:
      RunEventIngestor.publish(execution.stream, initial_events)
      outcome = await execute_agent_loop(
        agent,
        message,
        execution=execution,
        token_tracker=TokenTracker(),
      )
      try:
        committed = await settlement.settle_execution(
          thread_id=thread_id, run_id=run_id, outcome=outcome
        )
      except Exception:
        RunEventIngestor.notify_failure(execution.stream, "run_persistence_failed")
        raise

      RunEventIngestor.publish(execution.stream, committed.events, settlement=committed)
    except asyncio.CancelledError:
      # shutdown／外部 Task 取消不是用户的持久取消操作。
      RunEventIngestor.notify_failure(execution.stream, "execution_stopped")
      raise
    finally:
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
