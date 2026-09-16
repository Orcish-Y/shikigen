"""事件、完整消息的校验、幂等写入与查询。

insert_fact、event_by_key、read_events 供 RunStore 在持锁事务中调用，
这些底层方法不自行加锁或提交。
"""

import json
from typing import Any

import aiosqlite

from app.persistence.database import Database, _now, integrity_error
from app.run_state import CommittedEvent, EventWriteResult, MessageConflict, RunNotFound


class EventStore:
  def __init__(self, database: Database):
    self._db = database

  # todo 为什么有个 insert_fact 还有 append_event，又什么差别
  async def insert_fact(
    self,
    thread_id: str,
    run_id: str,
    event_type: str,
    category: str,
    event_key: str,
    content: Any,
  ) -> None:
    """仅在持有写锁和事务时调用；不自行提交。"""
    await self._db.connection.execute(
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
        self._json(content),
        _now(),
        thread_id,
      ),
    )

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
    """兼容 MessageJournal 的序号接口；所有消息仍经过统一校验。"""
    result = await self.append_committed_event(
      thread_id=thread_id,
      run_id=run_id,
      event_type=event_type,
      category=category,
      content=content,
      metadata=metadata,
      event_key=event_key,
    )
    return result.event["seq"]

  async def append_message(
    self,
    *,
    thread_id: str,
    run_id: str,
    content: dict[str, Any],
    metadata: dict[str, Any] | None = None,
  ) -> EventWriteResult:
    """按完整消息身份保存或返回原事实，不覆盖冲突内容。"""
    event_type, event_key = self.message_identity(content)
    return await self.append_committed_event(
      thread_id=thread_id,
      run_id=run_id,
      event_type=event_type,
      category="message",
      content=content,
      metadata=metadata,
      event_key=event_key,
    )

  async def append_committed_event(
    self,
    *,
    thread_id: str,
    run_id: str,
    event_type: str,
    category: str,
    content: Any,
    metadata: dict[str, Any] | None = None,
    event_key: str | None = None,
  ) -> EventWriteResult:
    """返回提交后的完整事件；生命周期仅由创建／结算事务写入。"""
    if category == "lifecycle" or event_type.startswith("run_"):
      raise ValueError("Lifecycle events require a run transaction")
    if category == "message" or event_type.endswith("_message"):
      expected_type, expected_key = self.message_identity(content)
      if (category, event_type, event_key) != ("message", expected_type, expected_key):
        raise ValueError("Message type, category and identity must agree")
    if metadata is not None and not isinstance(metadata, dict):
      raise ValueError("Event metadata must be an object")
    # 严格序列化，不把任意对象静默转换成字符串。
    content_json = self._json(content)
    metadata_json = self._json(metadata if metadata is not None else {})
    async with self._db.lock:
      try:
        await self._db.connection.execute("BEGIN IMMEDIATE")
        if not await self._run_exists(run_id, thread_id):
          raise RunNotFound("Run not found")
        existing = await self.event_by_key(thread_id, run_id, event_key)
        if existing is not None:
          if (
            existing["event_type"] != event_type
            or existing["category"] != category
            or self._json(existing["content"]) != content_json
            or self._json(existing["metadata"]) != metadata_json
          ):
            raise MessageConflict("Event identity already has different content")
          result = EventWriteResult(existing, inserted=False)
        else:
          cursor = await self._db.connection.execute(
            """INSERT INTO run_events(
              thread_id, run_id, seq, event_type, category, event_key,
              content_json, metadata_json, created_at
            ) SELECT ?, ?, COALESCE(MAX(seq), 0) + 1, ?, ?, ?, ?, ?, ?
            FROM run_events WHERE thread_id = ? RETURNING *""",
            (
              thread_id,
              run_id,
              event_type,
              category,
              event_key,
              content_json,
              metadata_json,
              _now(),
              thread_id,
            ),
          )
          rows = list(await cursor.fetchall())
          result = EventWriteResult(self._decode_event(rows[0]), inserted=True)
        await self._db.connection.commit()
        return result
      except aiosqlite.IntegrityError as error:
        await self._db.connection.rollback()
        raise integrity_error(error) from error
      except BaseException:
        await self._db.connection.rollback()
        raise

  @staticmethod
  def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)

  @staticmethod
  def message_identity(content: Any) -> tuple[str, str]:
    if not isinstance(content, dict):
      raise ValueError("Complete message must be an object")
    kind = content.get("type")
    if kind not in ("human", "ai", "tool"):
      raise ValueError("Unsupported complete message type")
    if not isinstance(content.get("content"), (str, list)):
      raise ValueError("Message content must be text or content blocks")
    identity = content.get("message_id")
    if kind == "ai" and not isinstance(content.get("tool_calls"), list):
      raise ValueError("AI message requires tool_calls")
    if kind == "tool":
      call_id = content.get("tool_call_id")
      if not isinstance(call_id, str) or not call_id.strip():
        raise ValueError("Tool message requires tool_call_id")
      if content.get("status") not in ("success", "error"):
        raise ValueError("Tool message requires success/error status")
      identity = identity or call_id
    if not isinstance(identity, str) or not identity.strip():
      raise ValueError("Message requires a stable identity")
    return f"{kind}_message", f"{kind}:{identity}"

  async def event_by_key(
    self,
    thread_id: str,
    run_id: str,
    event_key: str | None,
  ) -> CommittedEvent | None:
    cursor = await self._db.connection.execute(
      "SELECT * FROM run_events WHERE thread_id = ? AND run_id = ? AND event_key = ?",
      (thread_id, run_id, event_key),
    )
    row = await cursor.fetchone()
    return self._decode_event(row) if row is not None else None

  async def read_events(self, thread_id: str, run_id: str) -> list[CommittedEvent]:
    cursor = await self._db.connection.execute(
      "SELECT * FROM run_events WHERE thread_id = ? AND run_id = ? ORDER BY seq",
      (thread_id, run_id),
    )
    return [self._decode_event(row) for row in await cursor.fetchall()]

  async def list_messages_by_run(
    self,
    thread_id: str,
    run_id: str,
  ) -> list[CommittedEvent] | None:
    async with self._db.lock:
      return await self._list_messages_by_run(thread_id, run_id)

  async def _list_messages_by_run(
    self,
    thread_id: str,
    run_id: str,
  ) -> list[CommittedEvent] | None:
    # 先验证组合归属，从而区分“run 不存在”和“run 存在但还没有消息”。
    run_cursor = await self._db.connection.execute(
      "SELECT 1 FROM runs WHERE id = ? AND thread_id = ?",
      (run_id, thread_id),
    )
    if await run_cursor.fetchone() is None:
      return None

    cursor = await self._db.connection.execute(
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

  async def list_thread_messages(self, thread_id: str) -> list[CommittedEvent]:
    async with self._db.lock:
      return await self._list_thread_messages(thread_id)

  async def _list_thread_messages(self, thread_id: str) -> list[CommittedEvent]:
    cursor = await self._db.connection.execute(
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

  async def list_run_events(self, thread_id: str, run_id: str) -> list[CommittedEvent]:
    async with self._db.lock:
      if not await self._run_exists(run_id, thread_id):
        raise RunNotFound("Run not found")
      cursor = await self._db.connection.execute(
        """SELECT * FROM run_events WHERE thread_id = ? AND run_id = ?
        ORDER BY seq""",
        (thread_id, run_id),
      )
      return [self._decode_event(row) for row in await cursor.fetchall()]

  @staticmethod
  def _decode_event(row: aiosqlite.Row) -> CommittedEvent:
    return CommittedEvent(
      id=row["id"],
      thread_id=row["thread_id"],
      run_id=row["run_id"],
      seq=row["seq"],
      event_type=row["event_type"],
      category=row["category"],
      event_key=row["event_key"],
      content=json.loads(row["content_json"]),
      metadata=json.loads(row["metadata_json"]),
      created_at=row["created_at"],
    )

  async def _run_exists(self, run_id: str, thread_id: str) -> bool:
    cursor = await self._db.connection.execute(
      "SELECT 1 FROM runs WHERE id = ? AND thread_id = ?", (run_id, thread_id)
    )
    return await cursor.fetchone() is not None
