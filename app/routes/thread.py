from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, Response
from shikigen.contracts.runs import StorageConflict
from shikigen.contracts.threads import InvalidThreadCursor, ThreadPage
from shikigen.runtime import Runtime

from app.routes.queries import query_response_policy

router = APIRouter(prefix="/api/threads")


@router.get(
  "",
  summary="获取会话列表",
  description="按更新时间倒序获取会话及运行状态；limit 指定每页条数，cursor 可选。",
  response_description="会话列表",
  tags=["Threads"],
)
async def get_thread(
  request: Request,
  response: Response,
  limit: Annotated[int, Query(gt=0)],
  cursor: str | None = None,
) -> ThreadPage:
  runtime: Runtime = request.app.state.runtime
  with query_response_policy(response):
    if set(request.query_params) - {"limit", "cursor"} or any(
      len(request.query_params.getlist(key)) > 1 for key in ("limit", "cursor")
    ):
      raise InvalidThreadCursor("Only one limit and one optional cursor are accepted")
    return await runtime.threads.list_threads(limit=limit, cursor=cursor)


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
  response: Response,
) -> dict[str, object]:
  runtime: Runtime = request.app.state.runtime
  with query_response_policy(response):
    messages = await runtime.threads.list_thread_messages(thread_id)
  return {"data": messages}
