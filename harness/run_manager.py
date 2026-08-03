import asyncio
import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum

from harness.stream import Stream, StreamManager


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
    run_id = str(uuid.uuid4())
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

  def set_status(self, run_id: str, status: RunStatus) -> None:
    record = self.get(run_id)
    if record is None:
      raise ValueError(f"Run {run_id} not found")
    record.status = status

  def remove(self, run_id: str) -> None:
    if run_id in self._runs:
      del self._runs[run_id]
      self._stream_manager.remove(run_id)

  @property
  def active_count(self) -> int:
    return sum(
      1
      for record in self._runs.values()
      if record.status in (RunStatus.PENDING, RunStatus.RUNNING)
    )
