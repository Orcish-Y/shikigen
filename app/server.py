from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, nullcontext

from fastapi import FastAPI
from shikigen.runtime import Runtime, open_runtime

from app.routes import run, thread


def create_app(*, runtime: Runtime | None = None) -> FastAPI:
  """创建 HTTP 应用；传入的 runtime 由调用方持有并负责关闭。

  不传 runtime 时，由应用 lifespan 通过 open_runtime 装配和释放资源。
  外部 runtime 必须在整个 HTTP lifespan 期间保持可用。
  """

  @asynccontextmanager
  async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    context = open_runtime() if runtime is None else nullcontext(runtime)
    async with context as active_runtime:
      app.state.runtime = active_runtime
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
  return app


app = create_app()
