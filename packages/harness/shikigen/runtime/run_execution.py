"""本地 invocation 的启动、结算发布、取消与回收。

Run 的创建／审批接受必须先提交。持久状态由注入的事务 module 决定；
此 module 独占提交后发布与关闭的协调规则，不依赖观察者回收执行。
"""

import asyncio
import logging
from contextlib import nullcontext
from functools import partial
from typing import Any, Protocol
from weakref import WeakKeyDictionary

from langchain_core.messages import HumanMessage
from langgraph.types import Command

from shikigen.callback_handler import TokenTracker
from shikigen.contracts.runs import (
  CommittedEvent,
  CommittedRunState,
  ExecutionStopped,
  RunSnapshot,
  RunStatus,
  RunWriteResult,
)
from shikigen.contracts.stream import UsageData
from shikigen.core.execution import (
  ExecutionOutcome,
  ExecutionReason,
  ExecutionRegistry,
  RunExecution,
)
from shikigen.core.loop import execute_agent_loop
from shikigen.runtime.run_events import RunEventIngestor

logger = logging.getLogger(__name__)


class RunSettlement(Protocol):
  async def settle_execution(
    self,
    *,
    thread_id: str,
    run_id: str,
    outcome: ExecutionOutcome,
    error_code: str | None = None,
    invocation_seq: int | None = None,
    usage: UsageData | None = None,
  ) -> CommittedRunState:
    """原子提交状态、事实与用量；迟到结果必须服从已提交状态。"""
    ...

  async def cancel_run(self, *, thread_id: str, run_id: str) -> RunWriteResult:
    """原子取消；返回实际已提交的状态与本次新增事实。"""
    ...


class RunExecutionCoordinator:
  """持有本地执行的顺序约束；调用者只提交执行、取消或等待意图。

  Thread 业务排他由 RunService 串行化；这里的锁仅保护同一次 invocation
  的结算／取消提交、事实发布与关闭。shutdown 由应用在已接收操作完成后调用。
  """

  def __init__(
    self,
    registry: ExecutionRegistry,
    settlement: RunSettlement,
    ingestor: RunEventIngestor | None = None,
  ) -> None:
    self._registry = registry
    self._settlement = settlement
    self._ingestor = ingestor
    self._locks: WeakKeyDictionary[RunExecution, asyncio.Lock] = WeakKeyDictionary()
    self._cleanups: set[asyncio.Task[None]] = set()

  def _lock(self, execution: RunExecution) -> asyncio.Lock:
    return self._locks.setdefault(execution, asyncio.Lock())

  async def start(
    self,
    *,
    agent: Any,
    message: HumanMessage | Command,
    thread_id: str,
    run_id: str,
    initial_events: tuple[CommittedEvent, ...] = (),
    checkpoint: dict | None = None,
  ) -> RunExecution:
    """接手已提交的 invocation，统一装配回调并补偿启动失败。"""
    execution = RunExecution(
      run_id=run_id,
      thread_id=thread_id,
      replay_start_seq=min((e["seq"] for e in initial_events), default=0),
    )
    invocation_seq = next(
      (e["seq"] for e in reversed(initial_events) if e["event_type"] == "run_running"),
      None,
    )
    try:
      self._registry.install(execution)
      coroutine = self._execute(
        execution, agent, message, checkpoint, initial_events, invocation_seq
      )
      try:
        task = asyncio.create_task(coroutine, name=f"run:{run_id}")
      except BaseException:
        coroutine.close()
        raise
      execution.retain(task)
      task.add_done_callback(partial(self._on_done, execution))
    except BaseException as error:
      await self._finish(execution)
      if isinstance(error, Exception):
        await self._settlement.settle_execution(
          thread_id=thread_id,
          run_id=run_id,
          outcome=ExecutionOutcome(ExecutionReason.FAILED, error=error),
          error_code="resume_start_failed" if isinstance(message, Command) else None,
          invocation_seq=invocation_seq,
        )
      raise
    return execution

  async def _execute(
    self,
    execution: RunExecution,
    agent: Any,
    message: HumanMessage | Command,
    checkpoint: dict | None,
    initial_events: tuple[CommittedEvent, ...],
    invocation_seq: int | None,
  ) -> None:
    tracker = TokenTracker()
    identity = {"thread_id": execution.thread_id, "run_id": execution.run_id}
    try:
      RunEventIngestor.publish(execution.stream, initial_events)
      outcome = await execute_agent_loop(
        agent,
        message,
        execution=execution,
        checkpoint=checkpoint,
        token_tracker=tracker,
        ingest_delta=(
          partial(self._ingestor.ingest_delta, **identity)
          if self._ingestor is not None
          else None
        ),
        ingest_message=(
          partial(self._ingestor.ingest_message, **identity)
          if self._ingestor is not None
          else None
        ),
      )
      async with self._lock(execution):
        try:
          committed = await self._settlement.settle_execution(
            **identity,
            outcome=outcome,
            usage=tracker.summary(),
            invocation_seq=invocation_seq,
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
      # 进程关闭／强制停止不等于用户提交了 cancelled。
      RunEventIngestor.notify_failure(execution.stream, "execution_stopped")
      raise
    finally:
      await self._finish(execution)

  async def cancel(self, thread_id: str, run_id: str) -> RunSnapshot:
    """先提交并发布取消，再请求协作停止；没有本地执行也能持久取消。"""
    execution = self._registry.get(thread_id, run_id)
    async with self._lock(execution) if execution is not None else nullcontext():
      result = await self._settlement.cancel_run(thread_id=thread_id, run_id=run_id)
      if execution is not None and result.run["status"] == "cancelled":
        if result.events:
          RunEventIngestor.publish(
            execution.stream,
            result.events,
            settlement=CommittedRunState(RunStatus.CANCELLED, events=result.events),
          )
        execution.request_cancel()
      return result.run

  async def wait(self, execution: RunExecution) -> None:
    """等待执行及收尾；等待者取消不传播到执行，执行自身取消显式报错。"""
    task = execution.task
    if task is None:
      raise ValueError("Execution has not been started")
    try:
      await asyncio.shield(task)
    except asyncio.CancelledError:
      if not task.cancelled():
        raise
      await self._finish(execution)
      raise ExecutionStopped(
        "Local execution stopped without a committed result"
      ) from None

  async def drain(self, execution: RunExecution) -> None:
    """持久终态已释放槽位时，等待旧 Graph 退出；旧执行错误不阻塞新 Run。"""
    if execution.task is not None:
      await asyncio.shield(asyncio.gather(execution.task, return_exceptions=True))
    await self._finish(execution)

  async def _finish(self, execution: RunExecution) -> None:
    async with self._lock(execution):
      execution.stream.close()
      self._registry.remove(execution)

  def _on_done(self, execution: RunExecution, task: asyncio.Task[None]) -> None:
    # Task 可能在第一次运行前取消，或 finally 被再次取消；同一关闭协议兜底。
    if self._registry.get(execution.thread_id, execution.run_id) is execution:
      cleanup = asyncio.create_task(self._finish(execution))
      self._cleanups.add(cleanup)
      cleanup.add_done_callback(self._cleanups.discard)
    if not task.cancelled() and (error := task.exception()) is not None:
      logger.error(
        "Product execution failed: thread_id=%s run_id=%s",
        execution.thread_id,
        execution.run_id,
        exc_info=(type(error), error, error.__traceback__),
      )

  async def shutdown(self) -> None:
    """停止接收、停止本地 Task 并收完资源；不推断产品取消状态。"""
    executions = self._registry.stop_accepting()
    for execution in executions:
      execution.request_cancel()
      if execution.task is not None and not execution.task.done():
        execution.task.cancel()
    await asyncio.gather(
      *(e.task for e in executions if e.task is not None), return_exceptions=True
    )
    await asyncio.gather(*(self._finish(e) for e in executions))
    await asyncio.gather(*tuple(self._cleanups))
