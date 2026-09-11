import asyncio
import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum

from shikigen.stream import Stream, StreamManager


class RunStatus(StrEnum):
  PENDING = "pending"
  RUNNING = "running"
  COMPLETED = "completed"
  ERROR = "error"
  CANCELLED = "cancelled"


@dataclass
class RunRecord:
  run_id: str
  thread_id: str  # 对应用户/对话标识
  stream: Stream
  status: RunStatus = RunStatus.PENDING
  task: asyncio.Task | None = None  # 后台 asyncio Task
  abort_event: asyncio.Event = field(default_factory=asyncio.Event)
  created_at: float = field(default_factory=time.time)

  def start(self) -> None:
    """将新建的 run 转换为运行中。"""
    if self.status is not RunStatus.PENDING:
      raise RuntimeError(f"Cannot start run {self.run_id} from status {self.status}")
    self.status = RunStatus.RUNNING

  def finish(
    self,
    status: RunStatus,
    *,
    error: BaseException | None = None,
  ) -> None:
    """原子提交终态，并发布对应的最后一个事件。"""
    if status not in (
      RunStatus.COMPLETED,
      RunStatus.CANCELLED,
      RunStatus.ERROR,
    ):
      raise ValueError(f"Status {status} is not terminal")
    if self.status is not RunStatus.RUNNING:
      raise RuntimeError(f"Cannot finish run {self.run_id} from status {self.status}")
    if status is RunStatus.ERROR and error is None:
      raise ValueError("An error is required when finishing a run as error")
    if status is not RunStatus.ERROR and error is not None:
      raise ValueError("An error is only valid when finishing a run as error")

    self.status = status
    try:
      if status is RunStatus.ERROR:
        assert error is not None
        self.stream.publish("error", {"message": str(error)})
      elif status is RunStatus.COMPLETED:
        self.stream.publish("status", {"status": "completed"})
      else:
        self.stream.publish("status", {"status": "cancelled"})
    finally:
      self.stream.close()


class RunManager:
  def __init__(self, stream_manager: StreamManager):
    self._stream_manager = stream_manager
    self._runs: dict[str, RunRecord] = {}

  def get_active_by_thread(self, thread_id: str) -> RunRecord | None:
    for record in self._runs.values():
      if record.thread_id == thread_id and record.status in (
        RunStatus.PENDING,
        RunStatus.RUNNING,
      ):
        return record
    return None

  def create(self, thread_id: str) -> RunRecord:
    existing = self.get_active_by_thread(thread_id)
    if existing is not None:
      raise RuntimeError(
        f"Thread {thread_id} already has an active run: {existing.run_id}"
      )
    run_id = uuid.uuid4().hex
    stream = self._stream_manager.create(run_id)
    record = RunRecord(run_id=run_id, thread_id=thread_id, stream=stream)
    self._runs[run_id] = record
    return record

  def get(self, run_id: str) -> RunRecord | None:
    return self._runs.get(run_id)

  def cancel(self, run_id: str) -> None:
    record = self.get(run_id)
    if record is None:
      raise ValueError(f"Run {run_id} not found")
    record.abort_event.set()

  def remove(self, run_id: str) -> None:
    if run_id in self._runs:
      del self._runs[run_id]
      self._stream_manager.remove(run_id)

  async def release(self, run_id: str) -> None:
    """优雅停止并回收一个 run；重复释放不会报错。"""
    await self._release(run_id, force=False)

  def detach(self, run_id: str) -> None:
    """消费者离开后继续运行，后台任务结束（含持久化）时回收。"""
    record = self.get(run_id)
    if record is None:
      return

    def on_done(task: asyncio.Task) -> None:
      # 异常已由运行包装器持久化；取出异常避免无人等待任务的告警。
      if not task.cancelled():
        task.exception()
      self.remove(run_id)

    if record.task is None:
      self.remove(run_id)
    elif record.task.done():
      on_done(record.task)
    else:
      record.task.add_done_callback(on_done)

  async def _release(self, run_id: str, *, force: bool) -> None:
    record = self.get(run_id)
    if record is None:
      return

    task = record.task
    if task is not None and not task.done():
      if force:
        task.cancel()
      elif record.status in (RunStatus.PENDING, RunStatus.RUNNING):
        record.abort_event.set()

    try:
      if task is not None:
        await asyncio.gather(task, return_exceptions=True)
    except asyncio.CancelledError:
      # 调用方的取消作用域打断优雅收尾时，不能遗留后台 task。
      if task is not None and not task.done():
        task.cancel()
      raise
    finally:
      self.remove(run_id)

  async def shutdown(self) -> None:
    """取消并回收仍由 manager 持有的所有 run。"""
    run_ids = list(self._runs)
    await asyncio.gather(
      *(self._release(run_id, force=True) for run_id in run_ids),
      return_exceptions=True,
    )

  @property
  def active_count(self) -> int:
    return sum(
      1
      for record in self._runs.values()
      if record.status in (RunStatus.PENDING, RunStatus.RUNNING)
    )
