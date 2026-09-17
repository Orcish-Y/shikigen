"""产品 Run 的状态与应用错误；不依赖执行资源或传输协议。"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, TypedDict


class RunStatus(StrEnum):
  RUNNING = "running"
  INTERRUPTED = "interrupted"
  COMPLETED = "completed"
  ERROR = "error"
  CANCELLED = "cancelled"

  @property
  def terminal(self) -> bool:
    return self in (self.COMPLETED, self.ERROR, self.CANCELLED)


class RunError(RuntimeError):
  """可由非 HTTP 调用方直接处理的应用错误。"""


class ThreadNotFound(RunError):
  pass


class RunNotFound(RunError):
  pass


class StorageConflict(RunError):
  """持久身份或排他约束冲突，可由 HTTP 映射为 409。"""


class ThreadBusy(StorageConflict):
  pass


class MessageConflict(StorageConflict):
  """相同事件身份对应不同的完整事实。"""


class InvalidRunState(RunError):
  """持久状态或生命周期事实不支持本次操作。"""


class RunSnapshot(TypedDict):
  id: str
  thread_id: str
  status: str
  error: str | None
  error_code: str | None
  created_at: str
  updated_at: str
  completed_at: str | None


class CommittedEvent(TypedDict):
  id: int
  thread_id: str
  run_id: str
  seq: int
  event_type: str
  category: str
  event_key: str | None
  content: Any
  metadata: dict[str, Any]
  created_at: str


@dataclass(frozen=True, slots=True)
class EventWriteResult:
  event: CommittedEvent
  inserted: bool = field(compare=False)


@dataclass(frozen=True, slots=True)
class RunWriteResult:
  run: RunSnapshot
  events: tuple[CommittedEvent, ...]


class ExecutionStopped(RunError):
  """本地执行被停止；不代表已持久取消。"""


@dataclass(frozen=True, slots=True)
class CommittedRunState:
  """存储已提交的本次执行结果；interrupted 仍是非终态。"""

  status: RunStatus
  error: str | None = None
  error_code: str | None = None
  events: tuple[CommittedEvent, ...] = ()
  changed: bool = field(default=True, compare=False)

  def __post_init__(self) -> None:
    status = RunStatus(self.status)
    if status is RunStatus.RUNNING:
      raise ValueError("Execution settlement must finish or interrupt the invocation")
    object.__setattr__(self, "status", status)
