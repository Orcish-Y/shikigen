"""HTTP 与普通 Python 入口共享的资源装配。"""

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from shikigen.agent import create_lead_agent
from shikigen.app_config import AppConfig, load_app_config
from shikigen.checkpoint import make_checkpointer
from shikigen.execution import ExecutionRegistry

from app.lifecycle import ApplicationLifecycle
from app.persistence.chat_store import ChatStore, open_chat_store
from app.run_events import RunEventIngestor
from app.runtime import Runtime
from app.services.run import RunService
from app.services.thread import ThreadService


def assemble_runtime(
  *,
  config: AppConfig,
  agent: Any,
  chat_store: ChatStore,
  checkpointer: BaseCheckpointSaver | None = None,
  executions: ExecutionRegistry | None = None,
  ingestor: RunEventIngestor | None = None,
) -> Runtime:
  """将调用者提供的依赖组装为 Runtime；调用者负责关闭生命周期与存储。"""
  executions = executions if executions is not None else ExecutionRegistry()
  lifecycle = ApplicationLifecycle(executions)
  return Runtime(
    config=config,
    agent=agent,
    checkpointer=checkpointer,
    chat_store=chat_store,
    executions=executions,
    lifecycle=lifecycle,
    threads=ThreadService(store=chat_store, lifecycle=lifecycle),
    runs=RunService(
      agent=agent,
      store=chat_store,
      executions=executions,
      lifecycle=lifecycle,
      ingestor=ingestor,
    ),
  )


@asynccontextmanager
async def open_runtime(
  config: AppConfig | None = None,
  *,
  agent_factory: Callable[..., Awaitable[Any]] | None = None,
) -> AsyncIterator[Runtime]:
  """注入的工厂接收 config、middlewares 和 checkpointer，与默认工厂一致。"""
  app_config = config if config is not None else load_app_config()
  factory = agent_factory if agent_factory is not None else create_lead_agent
  async with (
    open_chat_store(Path(app_config.database.path).expanduser()) as store,
    make_checkpointer(app_config) as checkpointer,
  ):
    executions = ExecutionRegistry()
    ingestor = RunEventIngestor(store, executions)
    agent = await factory(
      config=app_config,
      middlewares=[],
      checkpointer=checkpointer,
    )
    runtime = assemble_runtime(
      config=app_config,
      agent=agent,
      chat_store=store,
      checkpointer=checkpointer,
      executions=executions,
      ingestor=ingestor,
    )
    try:
      yield runtime
    finally:
      await runtime.lifecycle.shutdown()
