"""各业务存储共享的连接、锁和 SQLite 错误转换。"""

import asyncio
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

import aiosqlite

from shikigen.contracts.runs import QueryUnavailable, StorageConflict, ThreadBusy


class Database:
  """同一连接的读写共用一把锁，防止读取未提交的数据。"""

  def __init__(self, connection: aiosqlite.Connection):
    self.connection = connection
    self.lock = asyncio.Lock()


def temporary_storage_error(error: Exception) -> bool:
  if isinstance(error, OSError):
    return True
  if isinstance(error, sqlite3.OperationalError):
    return getattr(error, "sqlite_errorcode", 0) & 0xFF in {
      sqlite3.SQLITE_BUSY,
      sqlite3.SQLITE_LOCKED,
      sqlite3.SQLITE_IOERR,
      sqlite3.SQLITE_CANTOPEN,
      sqlite3.SQLITE_FULL,
      sqlite3.SQLITE_READONLY,
    }
  return False


@contextmanager
def committed_query() -> Iterator[None]:
  """纯读查询的故障边界；只有暂时存储故障可重试，损坏原样抛出。"""
  try:
    yield
  except Exception as error:
    if temporary_storage_error(error):
      raise QueryUnavailable("Committed data unavailable; retry later") from error
    raise


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
