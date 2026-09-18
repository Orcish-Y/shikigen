from collections.abc import AsyncGenerator, AsyncIterator

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, ValidationError
from shikigen.execution import RunExecution

from app.run_contract import (
  MetadataData,
  MetadataEnvelope,
  RunSseEncoder,
  encode_sse,
  observation_error,
)
from app.run_state import RunNotFound, StorageConflict, ThreadNotFound
from app.runtime import Runtime

router = APIRouter(prefix="/api/threads/{thread_id}")


@router.get(
  "/runs/{run_id}/messages",
  summary="获取一次运行的消息",
  description="根据会话 ID 和运行 ID 获取该轮 Agent 产生的有序消息。",
  response_description="该次运行的消息记录",
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
  encoder = RunSseEncoder(execution.thread_id, execution.run_id)
  subscription = execution.stream.subscribe()
  try:
    # todo.  encode 是不是要收拢到同一个地方，保存和输出为相同的内容
    yield encode_sse(
      MetadataEnvelope(
        data=MetadataData(
          thread_id=execution.thread_id,
          run_id=execution.run_id,
          status="running",
        )
      )
    )
    async for event in subscription:
      if event.event == "metadata":
        continue
      try:
        frame = encoder.encode(event)
      except ValidationError:
        yield observation_error("invalid_event")
        return
      if frame is not None:
        yield frame
  finally:
    await subscription.aclose()


def _sse_response(content: AsyncIterator[str]) -> StreamingResponse:
  return StreamingResponse(
    content,
    media_type="text/event-stream",
    headers={
      "Cache-Control": "no-cache",
      "X-Accel-Buffering": "no",
    },
  )


@router.post(
  "/stream",
  summary="流式发送消息",
  description=("向指定会话发送一条消息，并通过 SSE 持续返回 Agent 运行事件。"),
  response_description="text/event-stream 格式的 Agent 运行事件流",
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
  return _sse_response(stream_run_events(execution))
