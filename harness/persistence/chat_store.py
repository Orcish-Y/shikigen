from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS threads (
  id TEXT PRIMARY KEY,
  user_id TEXT,
  title TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY,
  thread_id TEXT NOT NULL,
  status TEXT NOT NULL,
  error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  completed_at TEXT,
  FOREIGN KEY (thread_id) REFERENCES threads(id) ON DELETE CASCADE,
  UNIQUE (thread_id, id)
);

CREATE INDEX IF NOT EXISTS ix_runs_thread_created
  ON runs(thread_id, created_at);

CREATE TABLE IF NOT EXISTS run_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  thread_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  seq INTEGER NOT NULL,
  event_type TEXT NOT NULL,
  category TEXT NOT NULL,
  event_key TEXT,
  content_json TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  FOREIGN KEY (thread_id, run_id) REFERENCES runs(thread_id, id)
    ON DELETE CASCADE,
  UNIQUE (thread_id, seq)
);

CREATE INDEX IF NOT EXISTS ix_run_events_run_category_seq
  ON run_events(thread_id, run_id, category, seq);

"""


def _now() -> str:
  return datetime.now(UTC).isoformat()


class ChatStore:
  """Persist product-facing threads, runs, and ordered run events."""

  def __init__(self, connection: aiosqlite.Connection):
    self._connection = connection
    # 同一进程内串行化写操作，避免两个事件同时计算出相同的 thread seq。
    self._write_lock = asyncio.Lock()

  @classmethod
  async def open(cls, database_path: str | Path) -> ChatStore:
    """异步创建已连接且完成建表/迁移的 store。

    __init__ 不能 await，因此连接数据库的工作放在类方法中；使用 cls
    创建实例，也让子类调用 open() 时仍能得到子类实例。
    """
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = await aiosqlite.connect(path)
    connection.row_factory = aiosqlite.Row

    # 外键默认关闭；busy_timeout 减少短暂写竞争报错；WAL 允许读写并行。
    await connection.execute("PRAGMA foreign_keys = ON")
    await connection.execute("PRAGMA busy_timeout = 5000")
    await connection.execute("PRAGMA journal_mode = WAL")

    store = cls(connection)
    await store.setup()
    return store

  async def setup(self) -> None:
    await self._connection.executescript(SCHEMA)

    # 兼容已经由旧版本创建、尚未包含 event_key 的数据库。
    cursor = await self._connection.execute("PRAGMA table_info(run_events)")
    columns = {row[1] for row in await cursor.fetchall()}
    if "event_key" not in columns:
      await self._connection.execute("ALTER TABLE run_events ADD COLUMN event_key TEXT")

    # event_key 只约束可重放事件；NULL 仍允许普通事件重复写入。
    await self._connection.execute(
      """
      CREATE UNIQUE INDEX IF NOT EXISTS uq_run_events_event_key
      ON run_events(thread_id, run_id, event_key)
      WHERE event_key IS NOT NULL
      """
    )
    await self._connection.commit()

  async def close(self) -> None:
    await self._connection.close()

  async def create_thread(
    self,
    thread_id: str,
    *,
    user_id: str | None = None,
    title: str | None = None,
  ) -> None:
    now = _now()
    async with self._write_lock:
      await self._connection.execute(
        """
        INSERT INTO threads(id, user_id, title, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (thread_id, user_id, title, now, now),
      )
      await self._connection.commit()

  async def thread_exists(self, thread_id: str) -> bool:
    cursor = await self._connection.execute(
      "SELECT 1 FROM threads WHERE id = ?",
      (thread_id,),
    )
    return await cursor.fetchone() is not None

  async def list_threads(self) -> list[dict[str, Any]]:
    cursor = await self._connection.execute(
      """
      SELECT id, user_id, title, created_at, updated_at
      FROM threads
      ORDER BY updated_at DESC, id DESC
      """
    )
    return [dict(row) for row in await cursor.fetchall()]

  async def create_run(self, run_id: str, thread_id: str) -> None:
    now = _now()
    async with self._write_lock:
      await self._connection.execute(
        """
        INSERT INTO runs(id, thread_id, status, created_at, updated_at)
        VALUES (?, ?, 'pending', ?, ?)
        """,
        (run_id, thread_id, now, now),
      )
      await self._connection.commit()

  async def start_run(self, run_id: str, thread_id: str) -> None:
    await self._set_run_status(run_id, thread_id, "running")

  async def finish_run(
    self,
    run_id: str,
    thread_id: str,
    status: str,
    *,
    error: str | None = None,
  ) -> None:
    await self._set_run_status(
      run_id,
      thread_id,
      status,
      error=error,
      completed=True,
    )

  async def _set_run_status(
    self,
    run_id: str,
    thread_id: str,
    status: str,
    *,
    error: str | None = None,
    completed: bool = False,
  ) -> None:
    now = _now()
    completed_at = now if completed else None
    async with self._write_lock:
      cursor = await self._connection.execute(
        """
        UPDATE runs
        SET status = ?, error = ?, updated_at = ?, completed_at = ?
        WHERE id = ? AND thread_id = ?
        """,
        (status, error, now, completed_at, run_id, thread_id),
      )
      if cursor.rowcount != 1:
        await self._connection.rollback()
        raise ValueError(f"Run {run_id} does not belong to thread {thread_id}")

      await self._connection.execute(
        "UPDATE threads SET updated_at = ? WHERE id = ?",
        (now, thread_id),
      )
      await self._connection.commit()

  async def get_run(self, run_id: str, thread_id: str) -> dict[str, Any] | None:
    cursor = await self._connection.execute(
      """
      SELECT id, thread_id, status, error, created_at, updated_at, completed_at
      FROM runs
      WHERE id = ? AND thread_id = ?
      """,
      (run_id, thread_id),
    )
    row = await cursor.fetchone()
    return dict(row) if row is not None else None

  async def append_event(
    self,
    *,
    thread_id: str,
    run_id: str,
    event_type: str,
    category: str,
    content: Any,
    metadata: dict[str, Any] | None = None,
    event_key: str | None = None,
  ) -> int:
    """追加事件并返回它在 thread 内全局单调递增的序号。"""
    content_json = json.dumps(content, ensure_ascii=False, default=str)
    metadata_json = json.dumps(metadata or {}, ensure_ascii=False, default=str)

    async with self._write_lock:
      # 立即取得写锁，让“计算下一个 seq + 插入事件”成为一个原子操作。
      await self._connection.execute("BEGIN IMMEDIATE")
      try:
        cursor = await self._connection.execute(
          "SELECT COALESCE(MAX(seq), 0) + 1 FROM run_events WHERE thread_id = ?",
          (thread_id,),
        )
        row = await cursor.fetchone()
        assert row is not None
        seq = int(row[0])
        insert_cursor = await self._connection.execute(
          """
          INSERT INTO run_events(
            thread_id, run_id, seq, event_type, category, event_key,
            content_json, metadata_json, created_at
          )
          VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
          ON CONFLICT(thread_id, run_id, event_key) WHERE event_key IS NOT NULL
          DO NOTHING
          """,
          (
            thread_id,
            run_id,
            seq,
            event_type,
            category,
            event_key,
            content_json,
            metadata_json,
            _now(),
          ),
        )
        if insert_cursor.rowcount == 0:
          # checkpoint 重放命中相同 event_key 时，返回原事件的 seq。
          existing_cursor = await self._connection.execute(
            """
            SELECT seq FROM run_events
            WHERE thread_id = ? AND run_id = ? AND event_key = ?
            """,
            (thread_id, run_id, event_key),
          )
          existing = await existing_cursor.fetchone()
          assert existing is not None
          seq = int(existing[0])
        await self._connection.commit()
      except BaseException:
        await self._connection.rollback()
        raise

    return seq

  async def list_messages_by_run(
    self,
    thread_id: str,
    run_id: str,
  ) -> list[dict[str, Any]] | None:
    # 先验证组合归属，从而区分“run 不存在”和“run 存在但还没有消息”。
    run_cursor = await self._connection.execute(
      "SELECT 1 FROM runs WHERE id = ? AND thread_id = ?",
      (run_id, thread_id),
    )
    if await run_cursor.fetchone() is None:
      return None

    cursor = await self._connection.execute(
      """
      SELECT id, thread_id, run_id, seq, event_type, category, event_key,
             content_json, metadata_json, created_at
      FROM run_events
      WHERE thread_id = ? AND run_id = ? AND category = 'message'
      ORDER BY seq ASC
      """,
      (thread_id, run_id),
    )
    rows = await cursor.fetchall()
    return [self._decode_event(row) for row in rows]

  async def list_thread_messages(self, thread_id: str) -> list[dict[str, Any]]:
    cursor = await self._connection.execute(
      """
      SELECT id, thread_id, run_id, seq, event_type, category, event_key,
             content_json, metadata_json, created_at
      FROM run_events
      WHERE thread_id = ? AND category = 'message'
      ORDER BY seq ASC
      """,
      (thread_id,),
    )
    return [self._decode_event(row) for row in await cursor.fetchall()]

  @staticmethod
  def _decode_event(row: aiosqlite.Row) -> dict[str, Any]:
    event = dict(row)
    event["content"] = json.loads(event.pop("content_json"))
    event["metadata"] = json.loads(event.pop("metadata_json"))
    return event


@asynccontextmanager
async def open_chat_store(database_path: str | Path) -> AsyncGenerator[ChatStore, None]:
  store = await ChatStore.open(database_path)
  try:
    yield store
  finally:
    await store.close()
