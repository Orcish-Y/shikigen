"""本地事件缓存、订阅与广播。"""

import asyncio
from collections.abc import AsyncGenerator, Callable, Mapping
from typing import Any, Literal, cast, overload

from shikigen.contracts.stream import (
  ErrorData,
  EventData,
  EventName,
  MessageData,
  MetadataData,
  StatusData,
  StreamEvent,
  StreamEventVariant,
  StreamFailedData,
  ToolCallData,
  UsageData,
)


class _Subscription:
  """单个观察者的订阅；即使从未迭代，也能显式释放注册。"""

  def __init__(
    self,
    iterator: AsyncGenerator[StreamEventVariant, None],
    detach: Callable[[], None],
  ) -> None:
    self._iterator = iterator
    self._detach: Callable[[], None] | None = detach

  def __aiter__(self) -> "_Subscription":
    return self

  async def __anext__(self) -> StreamEventVariant:
    return await anext(self._iterator)

  async def aclose(self) -> None:
    """由消费方在 finally 中关闭；不与进行中的 __anext__ 并发调用。"""
    if self._detach is not None:
      self._detach()
      self._detach = None
    await self._iterator.aclose()


class Stream:
  """单个 run 的事件流。生产者 publish，消费者 subscribe 迭代。"""

  def __init__(self):
    self._events: list[StreamEventVariant] = []
    self._subscribers: set[asyncio.Queue[StreamEventVariant | None]] = set()
    self._closed = False
    self._next_id = 0

  @overload
  def publish(self, event: Literal["metadata"], data: MetadataData) -> None: ...

  @overload
  def publish(self, event: Literal["message"], data: MessageData) -> None: ...

  @overload
  def publish(self, event: Literal["tool_call"], data: ToolCallData) -> None: ...

  @overload
  def publish(self, event: Literal["error"], data: ErrorData) -> None: ...

  @overload
  def publish(self, event: Literal["usage"], data: UsageData) -> None: ...

  @overload
  def publish(self, event: Literal["status"], data: StatusData) -> None: ...

  @overload
  def publish(
    self, event: Literal["stream_failed"], data: StreamFailedData
  ) -> None: ...

  @overload
  def publish(
    self, event: Literal["durable_event"], data: Mapping[str, Any]
  ) -> None: ...

  def publish(self, event: EventName, data: EventData) -> None:
    """生产者发布事件。"""
    if self._closed:
      raise RuntimeError("Stream is closed")
    stream_event = StreamEvent(id=str(self._next_id), event=event, data=data)
    variant = cast(StreamEventVariant, stream_event)
    self._events.append(variant)
    for subscriber in self._subscribers:
      subscriber.put_nowait(variant)
    self._next_id += 1

  def subscribe(self) -> _Subscription:
    """同步注册并重放完整事件流；提前退出时由消费方调用 aclose。"""

    queue: asyncio.Queue[StreamEventVariant | None] = asyncio.Queue()
    for event in self._events:
      queue.put_nowait(event)

    if self._closed:
      queue.put_nowait(None)
    else:
      self._subscribers.add(queue)

    async def generator() -> AsyncGenerator[StreamEventVariant, None]:
      try:
        while True:
          event = await queue.get()
          if event is None:
            break

          yield event
      finally:
        self._subscribers.discard(queue)

    return _Subscription(generator(), lambda: self._subscribers.discard(queue))

  def close(self) -> None:
    """标记结束，唤醒所有等待的消费者。"""
    if self._closed:
      return

    self._closed = True
    for subscriber in self._subscribers:
      subscriber.put_nowait(None)


# StreamManager


class StreamManager:
  """管理所有 run 的 Stream 实例。"""

  def __init__(self):
    self.streams: dict[str, Stream] = {}

  def create(self, run_id: str) -> Stream:
    stream = Stream()
    self.streams[run_id] = stream
    return stream

  def get(self, run_id: str) -> Stream | None:
    return self.streams.get(run_id)

  def remove(self, run_id: str) -> None:
    if run_id in self.streams:
      del self.streams[run_id]
