from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from shikigen.agent import create_lead_agent
from shikigen.app_config import load_app_config
from shikigen.checkpoint import make_checkpointer
from shikigen.middleware.chat_persistence_middleware import ChatPersistenceMiddleware
from shikigen.run_manager import RunManager
from shikigen.stream import StreamManager

from app.persistence.chat_store import open_chat_store
from app.routes import run, thread
from app.runtime import ServerRuntime


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
  app_config = load_app_config()
  async with (
    open_chat_store(Path(app_config.database.path).expanduser()) as chat_store,
    make_checkpointer(app_config) as checkpointer,
  ):
    stream_manager = StreamManager()
    run_manager = RunManager(stream_manager)
    agent = await create_lead_agent(
      config=app_config,
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
