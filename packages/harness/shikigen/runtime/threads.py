"""Thread 创建与会话历史查询；供 HTTP 和普通 Python 入口共同使用。"""

import uuid
from typing import Any

from shikigen.contracts.runs import CommittedEvent, ThreadNotFound
from shikigen.persistence import ChatStore
from shikigen.runtime.lifecycle import ApplicationLifecycle


class ThreadService:
  def __init__(self, *, store: ChatStore, lifecycle: ApplicationLifecycle) -> None:
    self._store = store
    self._lifecycle = lifecycle

  async def create_thread(
    self,
    *,
    user_id: str | None = None,
    title: str | None = None,
  ) -> str:
    async def create() -> str:
      thread_id = uuid.uuid4().hex
      await self._store.create_thread(thread_id, user_id=user_id, title=title)
      return thread_id

    return await self._lifecycle.accept(create())

  async def list_threads(self) -> list[dict[str, Any]]:
    return await self._store.list_threads()

  async def list_thread_messages(self, thread_id: str) -> list[CommittedEvent]:
    if not await self._store.thread_exists(thread_id):
      raise ThreadNotFound("Thread not found")
    return await self._store.list_thread_messages(thread_id)
