"""只读内容流：持久前缀 + 一次 invocation 的完整缓存和实时订阅。"""

from __future__ import annotations

from collections.abc import AsyncGenerator, AsyncIterator
from typing import Protocol

from shikigen.stream import StreamEvent, StreamEventVariant

from app.run_state import CommittedEvent, RunSnapshot


class Subscription(Protocol):
  def __aiter__(self) -> AsyncIterator[StreamEventVariant]: ...
  async def __anext__(self) -> StreamEventVariant: ...
  async def aclose(self) -> None: ...


# todo. 之后看看能不能和stream合并
class RunObservation:
  """只读观察流。调用者拥有订阅；退出时需 aclose 释放（支持幂等关闭）。"""

  def __init__(
    self,
    run: RunSnapshot,
    history: list[CommittedEvent],
    subscription: Subscription | None = None,
  ) -> None:
    self.run = run
    self._subscription = subscription
    self._iterator = self._events(history)
    self._closed = False

  def __aiter__(self) -> RunObservation:
    return self

  async def __anext__(self) -> StreamEventVariant:
    if self._closed:
      raise StopAsyncIteration
    return await anext(self._iterator)

  async def _events(
    self, history: list[CommittedEvent]
  ) -> AsyncGenerator[StreamEventVariant, None]:
    try:
      for fact in history:
        yield StreamEvent(id="", event="durable_event", data=fact)
      if self._subscription is not None:
        async for event in self._subscription:
          yield event
    finally:
      if self._subscription is not None:
        await self._subscription.aclose()

  async def aclose(self) -> None:
    if self._closed:
      return
    self._closed = True
    # 异步生成器未启动时，aclose 不会进入它的 finally。
    if self._subscription is not None:
      await self._subscription.aclose()
      self._subscription = None
    await self._iterator.aclose()
