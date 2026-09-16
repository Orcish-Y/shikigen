import json
from collections.abc import AsyncGenerator, AsyncIterator

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from shikigen.execution import RunExecution
from shikigen.stream import StreamEventVariant

from app.run_state import RunNotFound, StorageConflict, ThreadNotFound
from app.runtime import Runtime

router = APIRouter(prefix="/api/threads/{thread_id}")


@router.get(
  "/runs/{run_id}/messages",
  summary="获取一次运行的消息",
  description="根据会话 ID 和运行 ID 获取该轮 Agent 产生的有序消息。",
  response_description="该次运行的消息记录",
  tags=["Messages"],
)
async def get_run_messages(
  thread_id: str,
  run_id: str,
  request: Request,
) -> dict[str, object]:
  runtime: Runtime = request.app.state.runtime
  try:
    messages = await runtime.runs.list_run_messages(thread_id, run_id)
  except RunNotFound as error:
    raise HTTPException(status_code=404, detail=str(error)) from error
  return {"data": messages}


class ChatRequest(BaseModel):
  """发起一次 Agent 对话所需的请求数据。"""

  message: str = Field(description="用户发送给 Agent 的消息")
  thread_id: str | None = Field(
    default=None,
    description="可选的会话 ID；路径中的 thread_id 是本接口的实际会话标识",
  )


async def stream_run_events(
  execution: RunExecution,
) -> AsyncGenerator[str, None]:
  encoder = RunJsonlEncoder()
  subscription = execution.stream.subscribe()
  try:
    async for event in subscription:
      yield encoder.encode(event)
  finally:
    await subscription.aclose()


class RunJsonlEncoder:
  """把通用 Agent 事件投影为一次 HTTP 响应内的 JSONL 输出数组事件。"""

  def __init__(self) -> None:
    self._next_output_index = 0
    self._active_message_output_index: int | None = None

  def encode(self, event: StreamEventVariant) -> str:
    event_name = event.event
    data: object = event.data
    output_index: int | None = None

    if event.event == "message":
      if event.data["done"]:
        event_name = "message.completed"
        data = {}
        output_index = (
          self._active_message_output_index
          if self._active_message_output_index is not None
          else self._reserve_output_index()
        )
        self._active_message_output_index = None
      else:
        event_name = "message.delta"
        data = {"delta": event.data["text"]}
        output_index = self._message_output_index()
    elif event.event == "tool_call":
      event_name = "tool_call.completed"
      output_index = self._reserve_output_index()
    elif event.event == "error":
      event_name = "run.error"
    elif event.event == "status":
      event_name = f"run.{event.data['status']}"

    return _format_jsonl(
      event.id,
      event_name,
      data,
      output_index=output_index,
    )

  def _message_output_index(self) -> int:
    if self._active_message_output_index is None:
      self._active_message_output_index = self._reserve_output_index()
    return self._active_message_output_index

  def _reserve_output_index(self) -> int:
    output_index = self._next_output_index
    self._next_output_index += 1
    return output_index


def _format_jsonl(
  event_id: str | int,
  event: str,
  data: object,
  *,
  output_index: int | None = None,
) -> str:
  payload: dict[str, object] = {
    "id": str(event_id),
    "event": event,
    "data": data,
  }
  if output_index is not None:
    payload["output_index"] = output_index
  return f"{json.dumps(jsonable_encoder(payload), ensure_ascii=False)}\n"


def _jsonl_response(content: AsyncIterator[str]) -> StreamingResponse:
  return StreamingResponse(
    content,
    media_type="application/x-ndjson",
    headers={
      "Cache-Control": "no-cache",
      "X-Accel-Buffering": "no",
    },
  )


@router.post(
  "/stream",
  summary="流式发送消息",
  description=("向指定会话发送一条消息，并通过 JSON Lines 持续返回 Agent 运行事件。"),
  response_description="application/x-ndjson 格式的 Agent 运行事件流",
  tags=["Messages"],
)
async def stream_chat(
  thread_id: str,
  body: ChatRequest,
  request: Request,
) -> StreamingResponse:
  runtime: Runtime = request.app.state.runtime
  try:
    execution = await runtime.runs.start_run(thread_id, body.message)
  except ThreadNotFound as error:
    raise HTTPException(status_code=404, detail=str(error)) from error
  except StorageConflict as error:
    raise HTTPException(
      status_code=status.HTTP_409_CONFLICT,
      detail=str(error),
    ) from error
  return _jsonl_response(stream_run_events(execution))
