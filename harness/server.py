import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from langchain.messages import HumanMessage
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel, Field

from harness.agent import create_lead_agent
from harness.app_config import load_app_config
from harness.callback_handler.token_tracker import TokenTracker
from harness.checkpoint.sqlite_provider import make_sqlite_checkpointer
from harness.loop import run_agent_loop
from harness.model import create_chat_model
from harness.persistence import ChatStore
from harness.persistence.chat_store import open_chat_store
from harness.run_manager import RunManager, RunRecord, RunStatus
from harness.stream import StreamManager
from middleware.chat_persistence_middleware import ChatPersistenceMiddleware
from text_safety import replace_surrogates
from tools.mcp_loader import load_mcp_tools
from tools.tool_registry import create_builtin_registry

checkpoint_db_path = Path(".shikigen/data/shikigen.db")


@dataclass(slots=True)
class ServerRuntime:
  """应用生命周期内由所有 HTTP 请求共享的 Agent 运行时。"""

  agent: CompiledStateGraph
  stream_manager: StreamManager
  run_manager: RunManager
  chat_store: ChatStore

  async def shutdown(self) -> None:
    """停止并回收服务器仍持有的所有 run。"""
    await self.run_manager.shutdown()


async def lifespan(app: FastAPI) -> AsyncIterator[None]:
  async with (
    open_chat_store(checkpoint_db_path) as chat_store,
    make_sqlite_checkpointer(checkpoint_db_path) as checkpointer,
  ):
    app_config = load_app_config()
    tool_registry = create_builtin_registry()
    tool_registry.register_many(await load_mcp_tools(app_config.mcp))
    stream_manager = StreamManager()
    run_manager = RunManager(stream_manager)
    model = create_chat_model(app_config.model)

    agent = create_lead_agent(
      model=model,
      tool_registry=tool_registry,
      middlewares=[ChatPersistenceMiddleware(chat_store)],
      checkpointer=checkpointer,
    )

    runtime = ServerRuntime(
      agent=agent,
      stream_manager=stream_manager,
      run_manager=run_manager,
      chat_store=chat_store,
    )
    app.state.runtime = runtime
    try:
      yield
    finally:
      await runtime.shutdown()


app = FastAPI(
  title="Shikigen Agent API",
  version="0.1.0",
  lifespan=lifespan,
)


@app.get(
  "/api/threads",
  summary="获取会话列表",
  description="获取当前用户可访问的全部 Agent 会话。",
  response_description="会话列表",
  tags=["Threads"],
)
async def get_thread(request: Request) -> list[dict[str, object]]:
  runtime: ServerRuntime = request.app.state.runtime
  return await runtime.chat_store.list_threads()


@app.post(
  "/api/threads",
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


@app.get(
  "/api/threads/{thread_id}/messages",
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


@app.get(
  "/api/threads/{thread_id}/runs/{run_id}/messages",
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
  runtime: ServerRuntime = request.app.state.runtime
  messages = await runtime.chat_store.list_messages_by_run(thread_id, run_id)
  if messages is None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
  return {"data": messages}


class ChatRequest(BaseModel):
  """发起一次 Agent 对话所需的请求数据。"""

  message: str = Field(description="用户发送给 Agent 的消息")
  thread_id: str | None = Field(
    default=None,
    description="可选的会话 ID；路径中的 thread_id 是本接口的实际会话标识",
  )


async def stream_run_events(
  record: RunRecord,
  run_manager: RunManager,
) -> AsyncIterator[str]:
  try:
    async for event in record.stream.subscribe():
      data = json.dumps(jsonable_encoder(event.data), ensure_ascii=False)
      yield f"event: {event.event}\ndata: {data}\n\n"
  finally:
    await run_manager.release(record.run_id)


async def run_and_persist_status(
  runtime: ServerRuntime,
  record: RunRecord,
  message: HumanMessage,
  tracker: TokenTracker,
) -> None:
  try:
    await run_agent_loop(
      runtime.agent,
      new_message=message,
      record=record,
      token_tracker=tracker,
    )
  except asyncio.CancelledError:
    await runtime.chat_store.finish_run(
      record.run_id,
      record.thread_id,
      RunStatus.CANCELLED,
    )
    raise
  except Exception as error:
    await runtime.chat_store.append_event(
      thread_id=record.thread_id,
      run_id=record.run_id,
      event_type="run_error",
      category="error",
      content={"message": str(error)},
      event_key=f"run_error:{record.run_id}",
    )
    await runtime.chat_store.finish_run(
      record.run_id,
      record.thread_id,
      RunStatus.ERROR,
      error=str(error),
    )
    raise
  else:
    await runtime.chat_store.finish_run(
      record.run_id,
      record.thread_id,
      record.status,
    )


@app.post(
  "/api/threads/{thread_id}/stream",
  summary="流式发送消息",
  description=(
    "向指定会话发送一条消息，并通过 Server-Sent Events 持续返回 Agent 运行事件。"
  ),
  response_description="text/event-stream 格式的 Agent 运行事件流",
  tags=["Messages"],
)
async def stream_chat(
  thread_id: str,
  body: ChatRequest,
  request: Request,
) -> StreamingResponse:
  runtime: ServerRuntime = request.app.state.runtime
  if not await runtime.chat_store.thread_exists(thread_id):
    raise HTTPException(
      status_code=status.HTTP_404_NOT_FOUND,
      detail="Thread not found",
    )

  record = runtime.run_manager.create(thread_id=thread_id)
  try:
    await runtime.chat_store.create_run(record.run_id, thread_id)
    await runtime.chat_store.start_run(record.run_id, thread_id)
  except BaseException:
    runtime.run_manager.remove(record.run_id)
    raise
  tracker = TokenTracker()
  agent_task = asyncio.create_task(
    run_and_persist_status(
      runtime,
      record,
      HumanMessage(
        id=uuid.uuid4().hex,
        content=replace_surrogates(body.message),
      ),
      tracker,
    )
  )

  record.task = agent_task

  return StreamingResponse(
    stream_run_events(record, runtime.run_manager),
    media_type="text/event-stream",
  )
