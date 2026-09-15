from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.composition import open_runtime
from app.routes import run, thread


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
  async with open_runtime() as runtime:
    app.state.runtime = runtime
    try:
      yield
    finally:
      del app.state.runtime


app = FastAPI(
  title="Shikigen Agent API",
  version="0.1.0",
  lifespan=lifespan,
)

app.include_router(thread.router)
app.include_router(run.router)
