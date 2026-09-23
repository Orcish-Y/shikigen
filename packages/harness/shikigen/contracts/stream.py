"""内存流事件与用量的数据模型，不包含广播实现。"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, NotRequired, TypedDict


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
