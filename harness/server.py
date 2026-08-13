import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, Request
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
from harness.run_manager import RunManager, RunRecord
from harness.stream import StreamManager
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

  async def shutdown(self) -> None:
    """停止并回收服务器仍持有的所有 run。"""
    await self.run_manager.shutdown()


async def lifespan(app: FastAPI) -> AsyncIterator[None]:
  async with make_sqlite_checkpointer(checkpoint_db_path) as checkpointer:
    app_config = load_app_config()
    tool_registry = create_builtin_registry()
    tool_registry.register_many(await load_mcp_tools(app_config.mcp))
    stream_manager = StreamManager()
    run_manager = RunManager(stream_manager)
    model = create_chat_model(app_config.model)

    agent = create_lead_agent(
      model=model,
      tool_registry=tool_registry,
      checkpointer=checkpointer,
    )

    runtime = ServerRuntime(
      agent=agent,
      stream_manager=stream_manager,
      run_manager=run_manager,
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
async def get_thread() -> list[dict[str, object]]:
  return []


@app.post(
  "/api/threads",
  summary="创建会话",
  description="创建一个新的 Agent 会话，并返回生成的会话 ID。",
  response_description="新会话的 ID",
  tags=["Threads"],
)
async def create_thread() -> dict[str, str]:
  thread_id = uuid.uuid4().hex
  return {"thread_id": thread_id}


@app.get(
  "/api/threads/{thread_id}/messages",
  summary="获取会话消息",
  description="根据会话 ID 获取该会话已有的聊天记录。",
  response_description="会话消息记录",
  tags=["Messages"],
)
async def get_thread_messages(thread_id: str) -> dict[str, object]:
  return {}


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
  record = runtime.run_manager.create(thread_id=thread_id)
  tracker = TokenTracker()
  agent_task = asyncio.create_task(
    run_agent_loop(
      runtime.agent,
      new_message=HumanMessage(content=replace_surrogates(body.message)),
      record=record,
      token_tracker=tracker,
    )
  )

  record.task = agent_task

  return StreamingResponse(
    stream_run_events(record, runtime.run_manager),
    media_type="text/event-stream",
  )
