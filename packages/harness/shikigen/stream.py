import asyncio
from collections.abc import AsyncGenerator, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal, NotRequired, TypedDict, cast, overload


class MetadataData(TypedDict):
  """运行元数据。"""

  run_id: str


class MessageChunkData(TypedDict):
  """一条逻辑消息的文本块。"""

  message_id: NotRequired[str]
  seq: NotRequired[int]
  text: str
  done: Literal[False]


class MessageDoneData(TypedDict):
  """一条逻辑消息已经结束。"""

  message_id: NotRequired[str]
  seq: NotRequired[int]
  text: Literal[""]
  done: Literal[True]


type MessageData = MessageChunkData | MessageDoneData


class ToolCallData(TypedDict):
  """工具调用事件载荷。"""

  message_id: NotRequired[str]
  tool_call_id: NotRequired[str]
  name: str
  input: Any
  output: Any


class ErrorData(TypedDict):
  """错误事件载荷。"""

  message: str


class StreamFailedData(TypedDict):
  """观察通道失败，不表示产品 Run 已进入 error 终态。"""

  code: str


class StatusData(TypedDict):
  """状态事件载荷。"""

  status: Literal["completed", "cancelled", "interrupted"]


class UsageModelData(TypedDict):
  """单个模型的 token 用量。"""

  input: int
  output: int
  calls: int


class UsageData(TypedDict):
  """一次 run 的 token 用量。"""

  total_input: int
  total_output: int
  total_tokens: int
  calls: int
  by_model: dict[str, UsageModelData]


type EventName = Literal[
  "metadata",
  "message",
  "tool_call",
  "error",
  "usage",
  "status",
  "stream_failed",
  "durable_event",
]
type EventData = (
  MetadataData
  | MessageData
  | ToolCallData
  | ErrorData
  | UsageData
  | StatusData
  | StreamFailedData
  | Mapping[str, Any]
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
  | StreamEvent[Literal["usage"], UsageData]
  | StreamEvent[Literal["status"], StatusData]
  | StreamEvent[Literal["stream_failed"], StreamFailedData]
  | StreamEvent[Literal["durable_event"], Mapping[str, Any]]
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
