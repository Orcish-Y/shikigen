from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import aiosqlite
from langchain_core.messages import HumanMessage
from shikigen.execution import ExecutionOutcome

from app.persistence.database import Database
from app.persistence.event_store import EventStore
from app.persistence.run_store import RunStore
from app.persistence.schema import setup_schema
from app.persistence.thread_store import ThreadStore
from app.run_state import (
  CommittedEvent,
  CommittedRunState,
  EventWriteResult,
  RunSnapshot,
  RunWriteResult,
)


class ChatStore:
  """产品持久化的统一入口，组合共享连接与锁的业务存储。"""

  def __init__(self, connection: aiosqlite.Connection):
    self._connection = connection
    database = Database(connection)
    self._threads = ThreadStore(database)
    self._events = EventStore(database)
    self._runs = RunStore(database, self._events)

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
      store = cls(connection)
      await store.setup()
      async with connection.execute("PRAGMA journal_mode = WAL") as cursor:
        await cursor.fetchall()
      return store
    except BaseException:
      await connection.close()
      raise

  async def setup(self) -> None:
    await setup_schema(self._connection)

  async def close(self) -> None:
    await self._connection.close()

  async def create_thread(
    self,
    thread_id: str,
    *,
    user_id: str | None = None,
    title: str | None = None,
  ) -> None:
    return await self._threads.create_thread(
      thread_id,
      user_id=user_id,
      title=title,
    )

  async def thread_exists(self, thread_id: str) -> bool:
    return await self._threads.thread_exists(
      thread_id,
    )

  async def list_threads(self) -> list[dict[str, Any]]:
    return await self._threads.list_threads()

  async def create_run(
    self,
    *,
    run_id: str,
    thread_id: str,
    entry_message: HumanMessage,
  ) -> RunWriteResult:
    """在一个写事务中检查排他并提交 Run、running 事实和入口消息。

    BEGIN IMMEDIATE 使本接口在多个连接间也串行检查。
    新库有 schema 排他约束；旧库升级属于 4B。
    """
    return await self._runs.create_run(
      run_id=run_id,
      thread_id=thread_id,
      entry_message=entry_message,
      fact_writer=self._insert_fact,
    )

  async def settle_execution(
    self,
    *,
    thread_id: str,
    run_id: str,
    outcome: ExecutionOutcome,
    error_code: str | None = None,
  ) -> CommittedRunState:
    """只有 running 能结算；已有终态或暂停事实原样返回，禁止覆盖。"""
    return await self._runs.settle_execution(
      thread_id=thread_id,
      run_id=run_id,
      outcome=outcome,
      error_code=error_code,
      fact_writer=self._insert_fact,
    )

  async def _insert_fact(
    self,
    thread_id: str,
    run_id: str,
    event_type: str,
    category: str,
    event_key: str,
    content: Any,
  ) -> None:
    """保留旧存储门面的事务注入钩子；调用方需持有写锁和事务。"""
    await self._events.insert_fact(
      thread_id,
      run_id,
      event_type,
      category,
      event_key,
      content,
    )

  async def get_run(self, run_id: str, thread_id: str) -> RunSnapshot | None:
    # 同一连接的读也必须等写事务结束，不能把尚未提交的状态暴露出去。
    return await self._runs.get_run(
      run_id,
      thread_id,
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
    return await self._events.append_event(
      thread_id=thread_id,
      run_id=run_id,
      event_type=event_type,
      category=category,
      content=content,
      metadata=metadata,
      event_key=event_key,
    )

  async def append_message(
    self,
    *,
    thread_id: str,
    run_id: str,
    content: dict[str, Any],
    metadata: dict[str, Any] | None = None,
  ) -> EventWriteResult:
    """按完整消息身份保存或返回原事实，不覆盖冲突内容。"""
    return await self._events.append_message(
      thread_id=thread_id,
      run_id=run_id,
      content=content,
      metadata=metadata,
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
    return await self._events.append_committed_event(
      thread_id=thread_id,
      run_id=run_id,
      event_type=event_type,
      category=category,
      content=content,
      metadata=metadata,
      event_key=event_key,
    )

  async def list_messages_by_run(
    self,
    thread_id: str,
    run_id: str,
  ) -> list[CommittedEvent] | None:
    return await self._events.list_messages_by_run(
      thread_id,
      run_id,
    )

  async def list_thread_messages(self, thread_id: str) -> list[CommittedEvent]:
    return await self._events.list_thread_messages(
      thread_id,
    )

  async def list_run_events(self, thread_id: str, run_id: str) -> list[CommittedEvent]:
    return await self._events.list_run_events(
      thread_id,
      run_id,
    )


@asynccontextmanager
async def open_chat_store(database_path: str | Path) -> AsyncGenerator[ChatStore, None]:
  store = await ChatStore.open(database_path)
  try:
    yield store
  finally:
    await store.close()
