from fastapi import APIRouter, HTTPException, Request
from shikigen.contracts.runs import StorageConflict, ThreadNotFound
from shikigen.runtime import Runtime

router = APIRouter(prefix="/api/threads")


@router.get(
  "",
  summary="获取会话列表",
  description="获取当前用户可访问的全部 Agent 会话。",
  response_description="会话列表",
  tags=["Threads"],
)
async def get_thread(request: Request) -> list[dict[str, object]]:
  runtime: Runtime = request.app.state.runtime
  return await runtime.threads.list_threads()


@router.post(
  "",
  summary="创建会话",
  description="创建一个新的 Agent 会话，并返回生成的会话 ID。",
  response_description="新会话的 ID",
  tags=["Threads"],
)
async def create_thread(request: Request) -> dict[str, str]:
  runtime: Runtime = request.app.state.runtime
  try:
    thread_id = await runtime.threads.create_thread()
  except StorageConflict as error:
    raise HTTPException(status_code=409, detail=str(error)) from error
  return {"thread_id": thread_id}


@router.get(
  "/{thread_id}/messages",
  summary="获取会话消息",
  description="根据会话 ID 获取该会话已有的聊天记录。",
  response_description="会话消息记录",
  tags=["Messages"],
)
async def get_thread_messages(
  thread_id: str,
  request: Request,
) -> dict[str, object]:
  runtime: Runtime = request.app.state.runtime
  try:
    messages = await runtime.threads.list_thread_messages(thread_id)
  except ThreadNotFound as error:
    raise HTTPException(status_code=404, detail=str(error)) from error
  return {"data": messages}
