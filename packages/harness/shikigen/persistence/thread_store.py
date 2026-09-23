"""会话的创建与查询。"""

from typing import Any

import aiosqlite

from shikigen.persistence.database import Database, _now, integrity_error


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

  async def list_threads(self) -> list[dict[str, Any]]:
    async with self._db.lock:
      return await self._list_threads()

  async def _list_threads(self) -> list[dict[str, Any]]:
    cursor = await self._db.connection.execute(
      """
      SELECT id, user_id, title, created_at, updated_at
      FROM threads
      ORDER BY updated_at DESC, id DESC
      """
    )
    return [dict(row) for row in await cursor.fetchall()]
