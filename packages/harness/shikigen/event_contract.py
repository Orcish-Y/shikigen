"""协议无关事件载荷。持久事件可查询恢复，message/tool_call 仅作实时预览。"""

from typing import Annotated, Literal

from pydantic import Field, JsonValue, TypeAdapter, model_validator

from shikigen.messages import CompleteMessage, Identity, StrictModel


class Lifecycle(StrictModel):
  status: Literal["running", "completed", "cancelled", "error", "interrupted"]
  message: str | None = None
  error_code: str | None = None
  checkpoint: dict[str, JsonValue] | None = None
  interrupts: list[dict[str, JsonValue]] | None = None


class DurableEvent(StrictModel):
  id: int
  thread_id: Identity
  run_id: Identity
  seq: Annotated[int, Field(gt=0)]
  event_type: str
  category: Literal["message", "lifecycle"]
  event_key: Identity
  content: CompleteMessage | Lifecycle
  metadata: dict[str, JsonValue]
  created_at: str

  @model_validator(mode="after")
  def matching_kind(self):
    if isinstance(self.content, Lifecycle):
      expected = ("lifecycle", f"run_{self.content.status}")
    else:
      expected = ("message", f"{self.content.type}_message")
    if (self.category, self.event_type) != expected:
      raise ValueError("Event category/type must match its content")
    return self


class Metadata(StrictModel):
  run_id: Identity


class Preview(StrictModel):
  seq: Annotated[int, Field(gt=0)] | None = None
  text: str
  done: bool
  message_id: Identity | None = None

  @model_validator(mode="after")
  def empty_end(self):
    if self.done and self.text:
      raise ValueError("End of preview must have empty text")
    return self


class ToolPreview(StrictModel):
  name: str
  input: JsonValue
  output: JsonValue
  tool_call_id: Identity | None = None
  message_id: Identity | None = None


class RunError(StrictModel):
  message: str


class ObservationError(StrictModel):
  code: Identity


class Status(StrictModel):
  status: Literal["completed", "cancelled", "interrupted"]


class ModelUsage(StrictModel):
  input: int
  output: int
  calls: int


class Usage(StrictModel):
  total_input: int
  total_output: int
  total_tokens: int
  calls: int
  by_model: dict[str, ModelUsage]


class MetadataEvent(StrictModel):
  event: Literal["metadata"]
  data: Metadata


class MessageEvent(StrictModel):
  event: Literal["message"]
  data: Preview


class ToolEvent(StrictModel):
  event: Literal["tool_call"]
  data: ToolPreview


class ErrorEvent(StrictModel):
  event: Literal["error"]
  data: RunError


class ObservationEvent(StrictModel):
  event: Literal["stream_failed"]
  data: ObservationError


class StatusEvent(StrictModel):
  event: Literal["status"]
  data: Status


class UsageEvent(StrictModel):
  event: Literal["usage"]
  data: Usage


class DurableStreamEvent(StrictModel):
  event: Literal["durable_event"]
  data: DurableEvent


EVENT = TypeAdapter(
  Annotated[
    MetadataEvent
    | MessageEvent
    | ToolEvent
    | ErrorEvent
    | ObservationEvent
    | StatusEvent
    | UsageEvent
    | DurableStreamEvent,
    Field(discriminator="event"),
  ]
)
