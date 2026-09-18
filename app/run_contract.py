"""SSE wire models and projection, independent of FastAPI and storage writes."""

import json
from typing import Annotated, Literal

from pydantic import Field, TypeAdapter
from shikigen.event_contract import EVENT, Lifecycle, Usage
from shikigen.messages import CompleteMessage, Identity, StrictModel
from shikigen.stream import StreamEventVariant


class MetadataData(StrictModel):
  thread_id: Identity
  run_id: Identity
  status: Literal["running", "completed", "cancelled", "interrupted", "error"]
  usage: Usage | None = None


class DeltaData(StrictModel):
  message_id: Identity
  field: Literal["content", "reasoning"]
  value: str


class MessageEvent(StrictModel):
  seq: Annotated[int, Field(gt=0)]
  created_at: str
  category: Literal["message"]
  event_type: Literal["created"]
  payload: CompleteMessage


class LifecycleEvent(StrictModel):
  seq: Annotated[int, Field(gt=0)]
  created_at: str
  category: Literal["lifecycle"]
  event_type: Literal["status_changed"]
  payload: Lifecycle


class StreamErrorData(StrictModel):
  code: Identity
  message: Identity
  recoverable: bool


class MetadataEnvelope(StrictModel):
  event: Literal["metadata"] = "metadata"
  data: MetadataData


class DeltaEnvelope(StrictModel):
  event: Literal["delta"] = "delta"
  data: DeltaData


class EventEnvelope(StrictModel):
  event: Literal["event"] = "event"
  data: Annotated[MessageEvent | LifecycleEvent, Field(discriminator="category")]


class ErrorEnvelope(StrictModel):
  event: Literal["error"] = "error"
  data: StreamErrorData


type SseEnvelope = (
  MetadataEnvelope | DeltaEnvelope | EventEnvelope | ErrorEnvelope
)
type SseEvent = SseEnvelope

SSE_EVENT = TypeAdapter(Annotated[SseEnvelope, Field(discriminator="event")])


def encode_sse(envelope: SseEnvelope) -> str:
  validated = SSE_EVENT.validate_python(envelope)
  data = json.dumps(
    validated.data.model_dump(mode="json", exclude_unset=True),
    ensure_ascii=False,
    allow_nan=False,
    separators=(",", ":"),
  )
  # No SSE id: the in-memory Stream id is not a durable replay cursor.
  return f"event: {validated.event}\ndata: {data}\n\n"


def observation_error(code: str) -> str:
  return encode_sse(
    ErrorEnvelope(
      data=StreamErrorData(
        code=code,
        message="Observation failed; read persisted run facts.",
        recoverable=True,
      )
    )
  )


class RunSseEncoder:
  """Project an execution stream into four SSE envelope kinds."""

  def __init__(self, thread_id: str, run_id: str):
    self.thread_id = thread_id
    self.run_id = run_id
    self.status: Literal[
      "running", "completed", "cancelled", "interrupted", "error"
    ] = "running"

  def encode(self, event: StreamEventVariant) -> str | None:
    parsed = EVENT.validate_python({"event": event.event, "data": event.data})
    if parsed.event == "durable_event":
      event_data = parsed.data
      return encode_sse(
        EventEnvelope.model_validate(
          {
            "data": {
              "seq": event_data.seq,
              "created_at": event_data.created_at,
              "category": event_data.category,
              "event_type": "created"
              if event_data.category == "message"
              else "status_changed",
              "payload": event_data.content.model_dump(
                mode="json", exclude_unset=True
              ),
            }
          }
        )
      )
    if parsed.event == "message":
      if parsed.data.done:
        return None
      return encode_sse(
        DeltaEnvelope.model_validate(
          {
            "data": {
              "message_id": parsed.data.message_id,
              "field": "content",
              "value": parsed.data.text,
            }
          }
        )
      )
    if parsed.event == "tool_call":
      # Complete tool results arrive as committed message events.
      return None
    if parsed.event == "stream_failed":
      return observation_error(parsed.data.code)
    if parsed.event == "status":
      self.status = parsed.data.status
    elif parsed.event == "error":
      self.status = "error"
    data = MetadataData(
      thread_id=self.thread_id,
      run_id=self.run_id,
      status=self.status,
    )
    if parsed.event == "usage":
      data.usage = parsed.data
    return encode_sse(MetadataEnvelope(data=data))
