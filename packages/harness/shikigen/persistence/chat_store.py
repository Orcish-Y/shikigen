from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiosqlite

from shikigen.contracts.runs import (
  CommittedEvent,
  EventWriteResult,
  RunSnapshot,
)
from shikigen.persistence.database import Database, integrity_error
from shikigen.persistence.event_store import EventStore
from shikigen.persistence.run_store import RunStore
from shikigen.persistence.schema import setup_schema
from shikigen.persistence.thread_store import ThreadStore


@dataclass(frozen=True, slots=True)
class RunTransaction:
  """仅在 ChatStore.transaction 上下文内使用，不调用自动加锁的接口。"""

  runs: RunStore
  events: EventStore


class ChatStore:
  """产品持久化的统一入口，组合共享连接与锁的业务存储。"""

  def __init__(self, connection: aiosqlite.Connection):
    self._connection = connection
    database = self._database = Database(connection)
    self._threads = ThreadStore(database)
    self._events = EventStore(database)
    self._runs = RunStore(database)

  @classmethod
  async def open(cls, database_path: str | Path) -> ChatStore:
    """异步创建已连接且完成当前 schema 建表的 store。

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

  @asynccontextmanager
  async def transaction(self) -> AsyncGenerator[RunTransaction, None]:
    """持锁开启写事务；事务内仅调用无需再次加锁的存取方法。

    BEGIN IMMEDIATE 串行化跨连接的读取与写入。上下文退出后才返回
    已提交结果；任何异常（包括任务取消）都会回滚。
    """
    async with self._database.lock:
      try:
        await self._connection.execute("BEGIN IMMEDIATE")
        yield RunTransaction(self._runs, self._events)
        await self._connection.commit()
      except aiosqlite.IntegrityError as error:
        await self._connection.rollback()
        raise integrity_error(error) from error
      except BaseException:
        await self._connection.rollback()
        raise

  async def list_nonterminal_runs(self) -> list[RunSnapshot]:
    return await self._runs.list_nonterminal_runs()

  async def get_run(self, run_id: str, thread_id: str) -> RunSnapshot | None:
    # 同一连接的读也必须等写事务结束，不能把尚未提交的状态暴露出去。
    return await self._runs.get_run(
      run_id,
      thread_id,
    )

  async def reserve_message_sequence(
    self, *, thread_id: str, run_id: str, message_id: str
  ) -> int:
    return await self._events.reserve_message_sequence(
      thread_id=thread_id, run_id=run_id, message_id=message_id
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
    """返回已提交事件的序号；所有消息仍经过统一校验。"""
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
