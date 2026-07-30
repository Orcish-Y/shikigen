import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Literal, TypedDict, cast, overload


class MetadataData(TypedDict):
  """运行元数据。"""

  run_id: str


class MessageData(TypedDict):
  """消息事件载荷。"""

  text: str


class ToolCallData(TypedDict):
  """工具调用事件载荷。"""

  name: str
  input: Any
  output: Any


class ErrorData(TypedDict):
  """错误事件载荷。"""

  message: str


class StatusData(TypedDict):
  """状态事件载荷。"""

  status: str


class EndData(TypedDict, total=False):
  """结束事件载荷。"""

  reason: str


type EventName = Literal[
  "metadata",
  "message",
  "tool_call",
  "error",
  "status",
  "end",
]
type EventData = (
  MetadataData | MessageData | ToolCallData | ErrorData | StatusData | EndData
)


@dataclass(frozen=True, slots=True)
class StreamEvent[EventNameT: EventName, EventDataT: EventData]:
  id: str  # 单调递增序号（支持断线重连）
  event: EventNameT
  data: EventDataT


type StreamEventVariant = (
  StreamEvent[Literal["metadata"], MetadataData]
  | StreamEvent[Literal["message"], MessageData]
  | StreamEvent[Literal["tool_call"], ToolCallData]
  | StreamEvent[Literal["error"], ErrorData]
  | StreamEvent[Literal["status"], StatusData]
  | StreamEvent[Literal["end"], EndData]
)


class Stream:
  """单个 run 的事件流。生产者 publish，消费者 subscribe 迭代。"""

  def __init__(self):
    self._queue: asyncio.Queue[StreamEventVariant | None] = asyncio.Queue()
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
  def publish(self, event: Literal["status"], data: StatusData) -> None: ...

  @overload
  def publish(self, event: Literal["end"], data: EndData) -> None: ...

  def publish(self, event: EventName, data: EventData) -> None:
    """生产者发布事件。"""
    if self._closed:
      raise RuntimeError("Stream is closed")
    stream_event = StreamEvent(id=str(self._next_id), event=event, data=data)
    self._queue.put_nowait(cast(StreamEventVariant, stream_event))
    self._next_id += 1

  def subscribe(self) -> AsyncIterator[StreamEventVariant]:
    """消费者订阅事件流。"""

    async def generator() -> AsyncIterator[StreamEventVariant]:
      while True:
        if self._closed and self._queue.empty():
          break
        event = await self._queue.get()
        if event is None:
          break

        yield event

    return generator()

  def close(self) -> None:
    """标记结束，唤醒等待的消费者。"""
    self._closed = True
    self._queue.put_nowait(None)


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
