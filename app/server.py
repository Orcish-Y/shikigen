from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import FastAPI
from shikigen.agent import create_lead_agent
from shikigen.app_config import load_app_config
from shikigen.middleware.chat_persistence_middleware import ChatPersistenceMiddleware
from shikigen.model import create_chat_model
from shikigen.run_manager import RunManager
from shikigen.stream import StreamManager
from shikigen.tools.mcp_loader import load_mcp_tools
from shikigen.tools.tool_registry import create_builtin_registry

from app.persistence.chat_store import open_chat_store
from app.persistence.sqlite_provider import make_sqlite_checkpointer
from app.routes import run, thread
from app.runtime import ServerRuntime

checkpoint_db_path = Path(".shikigen/data/shikigen.db")


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

app.include_router(thread.router)
app.include_router(run.router)
