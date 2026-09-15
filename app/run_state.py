"""产品 Run 的状态与应用错误；不依赖执行资源或传输协议。"""

from dataclasses import dataclass
from enum import StrEnum


class RunStatus(StrEnum):
  PENDING = "pending"  # 只为旧数据保留；新 Run 直接创建为 running。
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


class ThreadBusy(RunError):
  pass


class ExecutionStopped(RunError):
  """本地执行被停止；不代表已持久取消。"""


@dataclass(frozen=True, slots=True)
class CommittedRunState:
  """存储已提交的本次执行结果；interrupted 仍是非终态。"""

  status: RunStatus
  error: str | None = None

  def __post_init__(self) -> None:
    status = RunStatus(self.status)
    if status in (RunStatus.PENDING, RunStatus.RUNNING):
      raise ValueError("Execution settlement must finish or interrupt the invocation")
    object.__setattr__(self, "status", status)
