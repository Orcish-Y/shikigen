"""一次本地执行的资源与结果；不表示持久 Run 的生命周期。"""

import asyncio
from dataclasses import dataclass, field
from enum import StrEnum

from shikigen.core.stream import Stream


class ExecutionReason(StrEnum):
  COMPLETED = "completed"
  ABORTED = "aborted"
  FAILED = "failed"
  INTERRUPTED = "interrupted"


@dataclass(frozen=True, slots=True)
class ExecutionPause:
  """Graph 停留的 checkpoint 与中断信息，不解释产品审批策略。"""

  checkpoint: dict
  interrupts: tuple[dict, ...] = ()


@dataclass(frozen=True, slots=True)
class ExecutionOutcome:
  reason: ExecutionReason
  error: Exception | None = None
  pause: ExecutionPause | None = None

  def __post_init__(self) -> None:
    if (self.reason is ExecutionReason.FAILED) != (self.error is not None):
      raise ValueError("Only a failed execution must carry an error")
    if (self.reason is ExecutionReason.INTERRUPTED) != (self.pause is not None):
      raise ValueError("Only an interrupted execution must carry a pause")


@dataclass(eq=False, slots=True, weakref_slot=True)
class RunExecution:
  run_id: str
  thread_id: str
  stream: Stream = field(default_factory=Stream)
  abort_event: asyncio.Event = field(default_factory=asyncio.Event)
  # 本次 invocation 缓存覆盖的首个持久序号；不是客户端续传游标。
  replay_start_seq: int = 0
  # 应用编排串行提交、发布与关闭，避免取消事实被提前关闭的流吞掉。
  settlement_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
  _task: asyncio.Task[None] | None = field(default=None, init=False, repr=False)

  @property
  def task(self) -> asyncio.Task[None] | None:
    return self._task

  def retain(self, task: asyncio.Task[None]) -> None:
    """持有包含执行和持久化收尾的 Task，一次资源对象只绑定一次。"""
    if self._task is not None:
      raise RuntimeError("Execution already owns a task")
    self._task = task

  def request_cancel(self) -> None:
    """请求协作停止；不提交产品 cancelled，也不打断持久化收尾。"""
    self.abort_event.set()


class ExecutionRegistry:
  """本进程的执行资源索引；不承担数据库的 Thread 非终态排他。"""

  def __init__(self) -> None:
    self._executions: dict[str, RunExecution] = {}
    self._closing = False

  def install(self, execution: RunExecution) -> None:
    if self._closing:
      raise RuntimeError("Execution registry is shutting down")
    if execution.run_id in self._executions:
      raise RuntimeError(f"Run {execution.run_id} already has a local execution")
    self._executions[execution.run_id] = execution

  def get(self, thread_id: str, run_id: str) -> RunExecution | None:
    execution = self._executions.get(run_id)
    if execution is None or execution.thread_id != thread_id:
      return None
    return execution

  def for_thread(self, thread_id: str) -> tuple[RunExecution, ...]:
    return tuple(e for e in self._executions.values() if e.thread_id == thread_id)

  def remove(self, execution: RunExecution) -> None:
    """旧执行迟到的清理不能删除同 run_id 的新执行。"""
    if self._executions.get(execution.run_id) is execution:
      del self._executions[execution.run_id]

  async def shutdown(self) -> None:
    """强制停止本地 Task 并等待 finally；不推断产品取消状态。"""
    self._closing = True
    executions = list(self._executions.values())
    for execution in executions:
      execution.request_cancel()
      if execution.task is not None and not execution.task.done():
        execution.task.cancel()
    try:
      await asyncio.gather(
        *(item.task for item in executions if item.task is not None),
        return_exceptions=True,
      )
    finally:
      for execution in executions:
        execution.stream.close()
        self.remove(execution)
