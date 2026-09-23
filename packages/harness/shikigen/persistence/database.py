"""各业务存储共享的连接、锁和 SQLite 错误转换。"""

import asyncio
from datetime import UTC, datetime

import aiosqlite

from shikigen.runtime.run_state import StorageConflict, ThreadBusy


class Database:
  """同一连接的读写共用一把锁，防止读取未提交的数据。"""

  def __init__(self, connection: aiosqlite.Connection):
    self.connection = connection
    self.lock = asyncio.Lock()


def _now() -> str:
  return datetime.now(UTC).isoformat()


def integrity_error(error: aiosqlite.IntegrityError) -> Exception:
  if str(error) == "UNIQUE constraint failed: runs.thread_id":
    return ThreadBusy("Thread is busy with another run")
  if getattr(error, "sqlite_errorname", "") in (
    "SQLITE_CONSTRAINT_UNIQUE",
    "SQLITE_CONSTRAINT_PRIMARYKEY",
  ):
    return StorageConflict("Persistent identity already exists")
  return error
