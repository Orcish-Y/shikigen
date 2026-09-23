"""协议无关事件载荷。持久事件可查询恢复，message/tool_call 仅作实时预览。"""

from typing import Annotated, Literal

from pydantic import Field, JsonValue, TypeAdapter, model_validator

from shikigen.contracts.messages import CompleteMessage, Identity, StrictModel


class Lifecycle(StrictModel):
  status: Literal["running", "completed", "cancelled", "error", "interrupted"]
  message: str | None = None
  error_code: str | None = None


class CheckpointCoordinate(StrictModel):
  thread_id: Identity
  checkpoint_ns: str
  checkpoint_id: Identity


class CheckpointConfig(StrictModel):
  configurable: CheckpointCoordinate


class PendingInterrupt(StrictModel):
  id: Identity
  namespace: str
  value: JsonValue


class ApprovalRequired(StrictModel):
  status: Literal["required"] = "required"
  checkpoint: CheckpointConfig
  interrupts: Annotated[list[PendingInterrupt], Field(min_length=1)]

  @model_validator(mode="after")
  def unique_interrupts(self):
    ids = [item.id for item in self.interrupts]
    if len(set(ids)) != len(ids):
      raise ValueError("Interrupt IDs must be unique")
    if self.checkpoint.configurable.checkpoint_ns:
      raise ValueError("Approval requires a root checkpoint")
    return self


class ApproveDecision(StrictModel):
  type: Literal["approve"]


class RejectDecision(StrictModel):
  type: Literal["reject"]
  message: str | None = None


class InterruptResponse(StrictModel):
  decisions: Annotated[
    list[Annotated[ApproveDecision | RejectDecision, Field(discriminator="type")]],
    Field(min_length=1),
  ]


class ApprovalSubmission(StrictModel):
  responses: Annotated[dict[Identity, InterruptResponse], Field(min_length=1)]


class ApprovalResolved(ApprovalSubmission):
  status: Literal["resolved"] = "resolved"
  checkpoint: CheckpointConfig


class ApprovalInvalidated(StrictModel):
  status: Literal["invalidated"] = "invalidated"
  checkpoint: CheckpointConfig
  interrupt_ids: Annotated[list[Identity], Field(min_length=1)]
  reason: Literal["run_cancelled"] = "run_cancelled"


class DurableEvent(StrictModel):
  id: int
  thread_id: Identity
  run_id: Identity
  seq: Annotated[int, Field(gt=0)]
  event_type: str
  category: Literal["message", "lifecycle", "approval"]
  event_key: Identity
  content: (
    CompleteMessage
    | Lifecycle
    | ApprovalRequired
    | ApprovalResolved
    | ApprovalInvalidated
  )
  metadata: dict[str, JsonValue]
  created_at: str

  @model_validator(mode="after")
  def matching_kind(self):
    if isinstance(
      self.content, (ApprovalRequired, ApprovalResolved, ApprovalInvalidated)
    ):
      expected = ("approval", f"approval_{self.content.status}")
    elif isinstance(self.content, Lifecycle):
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
