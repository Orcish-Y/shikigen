import uuid

from fastapi import APIRouter, HTTPException, Request, status

from app.runtime import ServerRuntime

router = APIRouter(prefix="/api/threads")


@router.get(
  "",
  summary="获取会话列表",
  description="获取当前用户可访问的全部 Agent 会话。",
  response_description="会话列表",
  tags=["Threads"],
)
async def get_thread(request: Request) -> list[dict[str, object]]:
  runtime: ServerRuntime = request.app.state.runtime
  return await runtime.chat_store.list_threads()


@router.post(
  "",
  summary="创建会话",
  description="创建一个新的 Agent 会话，并返回生成的会话 ID。",
  response_description="新会话的 ID",
  tags=["Threads"],
)
async def create_thread(request: Request) -> dict[str, str]:
  runtime: ServerRuntime = request.app.state.runtime
  thread_id = uuid.uuid4().hex
  # 这里可能需要修改，创建的时候不要直接建表，这样子可能有很多空表???
  # 不过有空表也不错，可以在一开始就重命名
  await runtime.chat_store.create_thread(thread_id)
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
  runtime: ServerRuntime = request.app.state.runtime
  if not await runtime.chat_store.thread_exists(thread_id):
    raise HTTPException(
      status_code=status.HTTP_404_NOT_FOUND,
      detail="Thread not found",
    )
  messages = await runtime.chat_store.list_thread_messages(thread_id)
  return {"data": messages}
