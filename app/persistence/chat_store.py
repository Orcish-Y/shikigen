from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite
from langchain_core.messages import HumanMessage
from shikigen.execution import ExecutionOutcome, ExecutionReason

from app.run_state import (
  CommittedRunState,
  RunNotFound,
  RunStatus,
  ThreadBusy,
  ThreadNotFound,
)

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

    try:
      # 外键默认关闭；busy_timeout 减少短暂写竞争报错；WAL 允许读写并行。
      await connection.execute("PRAGMA foreign_keys = ON")
      await connection.execute("PRAGMA busy_timeout = 5000")
      await connection.execute("PRAGMA journal_mode = WAL")
      store = cls(connection)
      await store.setup()
      return store
    except BaseException:
      await connection.close()
      raise

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
      try:
        await self._connection.execute(
          """
          INSERT INTO threads(id, user_id, title, created_at, updated_at)
          VALUES (?, ?, ?, ?, ?)
          """,
          (thread_id, user_id, title, now, now),
        )
        await self._connection.commit()
      except BaseException:
        await self._connection.rollback()
        raise

  async def thread_exists(self, thread_id: str) -> bool:
    async with self._write_lock:
      cursor = await self._connection.execute(
        "SELECT 1 FROM threads WHERE id = ?",
        (thread_id,),
      )
      return await cursor.fetchone() is not None

  async def list_threads(self) -> list[dict[str, Any]]:
    async with self._write_lock:
      return await self._list_threads()

  async def _list_threads(self) -> list[dict[str, Any]]:
    cursor = await self._connection.execute(
      """
      SELECT id, user_id, title, created_at, updated_at
      FROM threads
      ORDER BY updated_at DESC, id DESC
      """
    )
    return [dict(row) for row in await cursor.fetchall()]

  async def _insert_fact(
    self,
    thread_id: str,
    run_id: str,
    event_type: str,
    category: str,
    event_key: str,
    content: Any,
  ) -> None:
    """仅在持有写锁和事务时调用；不自行提交。"""
    await self._connection.execute(
      """
      INSERT INTO run_events(
        thread_id, run_id, seq, event_type, category, event_key,
        content_json, metadata_json, created_at
      )
      SELECT ?, ?, COALESCE(MAX(seq), 0) + 1, ?, ?, ?, ?, '{}', ?
      FROM run_events WHERE thread_id = ?
      """,
      (
        thread_id,
        run_id,
        event_type,
        category,
        event_key,
        json.dumps(content, ensure_ascii=False),
        _now(),
        thread_id,
      ),
    )

  async def create_run(
    self,
    *,
    run_id: str,
    thread_id: str,
    entry_message: HumanMessage,
  ) -> None:
    """在一个写事务中检查排他并提交 Run、running 事实和入口消息。

    BEGIN IMMEDIATE 使本接口在多个连接间也串行检查。
    schema 级约束升级仍属于数据迁移步骤。
    """
    if not entry_message.id:
      raise ValueError("Entry message requires a stable id")
    async with self._write_lock:
      try:
        await self._connection.execute("BEGIN IMMEDIATE")
        cursor = await self._connection.execute(
          "SELECT 1 FROM threads WHERE id = ?", (thread_id,)
        )
        if await cursor.fetchone() is None:
          raise ThreadNotFound("Thread not found")
        cursor = await self._connection.execute(
          """
          SELECT 1 FROM runs WHERE thread_id = ?
          AND status NOT IN ('completed', 'error', 'cancelled') LIMIT 1
          """,
          (thread_id,),
        )
        if await cursor.fetchone() is not None:
          raise ThreadBusy("Thread is busy with another run")
        now = _now()
        await self._connection.execute(
          """INSERT INTO runs(id, thread_id, status, created_at, updated_at)
          VALUES (?, ?, 'running', ?, ?)""",
          (run_id, thread_id, now, now),
        )
        await self._insert_fact(
          thread_id,
          run_id,
          "run_running",
          "lifecycle",
          f"running:{run_id}",
          {"status": "running"},
        )
        await self._insert_fact(
          thread_id,
          run_id,
          "human_message",
          "message",
          f"human:{entry_message.id}",
          {
            "type": "human",
            "content": entry_message.content,
            "message_id": entry_message.id,
          },
        )
        await self._connection.execute(
          "UPDATE threads SET updated_at = ? WHERE id = ?", (now, thread_id)
        )
        await self._connection.commit()
      except BaseException:
        await self._connection.rollback()
        raise

  async def settle_execution(
    self,
    *,
    thread_id: str,
    run_id: str,
    outcome: ExecutionOutcome,
  ) -> CommittedRunState:
    """只有 running 能结算；已有终态或暂停事实原样返回，禁止覆盖。"""
    target = {
      ExecutionReason.COMPLETED: RunStatus.COMPLETED,
      ExecutionReason.ABORTED: RunStatus.CANCELLED,
      ExecutionReason.FAILED: RunStatus.ERROR,
      ExecutionReason.INTERRUPTED: RunStatus.INTERRUPTED,
    }[outcome.reason]
    error = str(outcome.error) if outcome.error is not None else None
    async with self._write_lock:
      try:
        await self._connection.execute("BEGIN IMMEDIATE")
        cursor = await self._connection.execute(
          "SELECT status, error FROM runs WHERE id = ? AND thread_id = ?",
          (run_id, thread_id),
        )
        row = await cursor.fetchone()
        if row is None:
          raise RunNotFound("Run not found")
        if row["status"] != RunStatus.RUNNING:
          committed = CommittedRunState(RunStatus(row["status"]), row["error"])
          await self._connection.commit()
          return committed
        now = _now()
        cursor = await self._connection.execute(
          """UPDATE runs SET status = ?, error = ?, updated_at = ?, completed_at = ?
          WHERE id = ? AND thread_id = ? AND status = 'running'""",
          (target, error, now, now if target.terminal else None, run_id, thread_id),
        )
        if cursor.rowcount != 1:
          raise RuntimeError("Run state changed during settlement")
        content: dict[str, Any] = {"status": target}
        if error is not None:
          content["message"] = error
        if outcome.pause is not None:
          content["checkpoint"] = outcome.pause.checkpoint
          content["interrupts"] = outcome.pause.interrupts
        await self._insert_fact(
          thread_id,
          run_id,
          f"run_{target}",
          "lifecycle",
          f"settled:{run_id}",
          content,
        )
        await self._connection.execute(
          "UPDATE threads SET updated_at = ? WHERE id = ?", (now, thread_id)
        )
        await self._connection.commit()
        return CommittedRunState(target, error)
      except BaseException:
        await self._connection.rollback()
        raise

  async def get_run(self, run_id: str, thread_id: str) -> dict[str, Any] | None:
    # 同一连接的读也必须等写事务结束，不能把尚未提交的状态暴露出去。
    async with self._write_lock:
      return await self._get_run(run_id, thread_id)

  async def _get_run(self, run_id: str, thread_id: str) -> dict[str, Any] | None:
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
    async with self._write_lock:
      return await self._list_messages_by_run(thread_id, run_id)

  async def _list_messages_by_run(
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
    async with self._write_lock:
      return await self._list_thread_messages(thread_id)

  async def _list_thread_messages(self, thread_id: str) -> list[dict[str, Any]]:
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

  async def list_run_events(self, thread_id: str, run_id: str) -> list[dict[str, Any]]:
    async with self._write_lock:
      if await self._get_run(run_id, thread_id) is None:
        raise RunNotFound("Run not found")
      cursor = await self._connection.execute(
        """SELECT * FROM run_events WHERE thread_id = ? AND run_id = ?
        ORDER BY seq""",
        (thread_id, run_id),
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
