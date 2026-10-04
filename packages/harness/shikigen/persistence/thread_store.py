"""会话的创建与查询。"""

import base64
import binascii
import json
import re
from datetime import datetime

import aiosqlite

from shikigen.contracts.threads import InvalidThreadCursor, ThreadPage, ThreadSummary
from shikigen.persistence.database import Database, _now, integrity_error


def _encode_cursor(updated_at: str, thread_id: str) -> str:
  value = json.dumps([1, updated_at, thread_id], separators=(",", ":"))
  return base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[str, str]:
  try:
    if len(cursor) > 4096 or not re.fullmatch(r"[A-Za-z0-9_-]+", cursor):
      raise ValueError
    raw = base64.b64decode(
      cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True
    )
    value = json.loads(raw)
    if not isinstance(value, list) or len(value) != 3:
      raise ValueError
    version, updated_at, thread_id = value
    if type(version) is not int or version != 1:
      raise ValueError
    if (
      not isinstance(updated_at, str) or not isinstance(thread_id, str) or not thread_id
    ):
      raise ValueError
    if datetime.fromisoformat(updated_at).tzinfo is None:
      raise ValueError
    if _encode_cursor(updated_at, thread_id) != cursor:
      raise ValueError
    return updated_at, thread_id
  except (ValueError, TypeError, binascii.Error, UnicodeError, RecursionError) as error:
    raise InvalidThreadCursor("Invalid conversation cursor; reload the list") from error


class ThreadStore:
  def __init__(self, database: Database):
    self._db = database

  async def create_thread(
    self,
    thread_id: str,
    *,
    user_id: str | None = None,
    title: str | None = None,
  ) -> None:
    now = _now()
    async with self._db.lock:
      try:
        await self._db.connection.execute(
          """
          INSERT INTO threads(id, user_id, title, created_at, updated_at)
          VALUES (?, ?, ?, ?, ?)
          """,
          (thread_id, user_id, title, now, now),
        )
        await self._db.connection.commit()
      except aiosqlite.IntegrityError as error:
        await self._db.connection.rollback()
        raise integrity_error(error) from error
      except BaseException:
        await self._db.connection.rollback()
        raise

  async def thread_exists(self, thread_id: str) -> bool:
    async with self._db.lock:
      cursor = await self._db.connection.execute(
        "SELECT 1 FROM threads WHERE id = ?",
        (thread_id,),
      )
      return await cursor.fetchone() is not None

  async def list_threads(self, *, limit: int, cursor: str | None = None) -> ThreadPage:
    if type(limit) is not int or limit <= 0:
      raise ValueError("limit must be a positive integer")
    boundary = _decode_cursor(cursor) if cursor is not None else None
    async with self._db.lock:
      # 一个 SELECT 读取摘要与状态。首次 running 事件的 seq 表示发起顺序，
      # 即使时间相同、旧 Run 晚结算或原 Run 多次恢复，也不会选错最近发起身份。
      # 以十进制文本绑定，再由 SQLite CAST 处理整数范围，避免大 limit 的绑定溢出。
      result = await self._db.connection.execute(
        """
        SELECT t.*, r.id AS run_id, r.status AS run_status
        FROM threads t LEFT JOIN runs r ON r.id = (
          SELECT candidate.id FROM runs candidate WHERE candidate.thread_id = t.id
          ORDER BY candidate.status IN ('running', 'interrupted') DESC,
            (SELECT MIN(e.seq) FROM run_events e
             WHERE e.thread_id = candidate.thread_id AND e.run_id = candidate.id
               AND e.event_type = 'run_running') DESC,
            candidate.created_at DESC, candidate.id DESC
          LIMIT 1
        )
        """
        + (" WHERE (t.updated_at, t.id) < (?, ?)" if boundary else "")
        + " ORDER BY t.updated_at DESC, t.id DESC LIMIT CAST(? AS INTEGER)",
        (*(boundary or ()), str(limit + 1)),
      )
      rows = list(await result.fetchall())
      data = [
        ThreadSummary(
          id=row["id"],
          user_id=row["user_id"],
          title=row["title"],
          created_at=row["created_at"],
          updated_at=row["updated_at"],
          run_id=row["run_id"],
          run_status=row["run_status"],
        )
        for row in rows[:limit]
      ]
      return ThreadPage(
        data=data,
        next_cursor=(
          _encode_cursor(data[-1]["updated_at"], data[-1]["id"])
          if len(rows) > limit
          else None
        ),
      )
