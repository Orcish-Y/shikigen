"""会话列表的公开分页结果。"""

from typing import TypedDict

from shikigen.contracts.runs import RunStatus


class InvalidThreadCursor(ValueError):
  """游标无法解释为本版本的会话排序边界。"""


class ThreadSummary(TypedDict):
  id: str
  user_id: str | None
  title: str | None
  created_at: str
  updated_at: str
  run_id: str | None
  run_status: RunStatus | None


class ThreadPage(TypedDict):
  data: list[ThreadSummary]
  next_cursor: str | None
