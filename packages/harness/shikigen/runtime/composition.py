"""HTTP 与普通 Python 入口共享的资源装配。"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver

from shikigen.app_config import AppConfig, load_app_config
from shikigen.checkpoint import make_checkpointer
from shikigen.core.agent import create_lead_agent
from shikigen.core.approval import build_approval_middleware
from shikigen.core.execution import ExecutionRegistry
from shikigen.persistence.chat_store import ChatStore, open_chat_store
from shikigen.runtime.lifecycle import ApplicationLifecycle
from shikigen.runtime.run_events import RunEventIngestor
from shikigen.runtime.runs import RunService
from shikigen.runtime.threads import ThreadService
from shikigen.tools import create_builtin_registry
from shikigen.tools.mcp_loader import load_mcp_tools


@dataclass(frozen=True, slots=True)
class Runtime:
  """运行配置与已装配依赖；业务操作和生命周期由对应模块负责。"""

  config: AppConfig
  agent: Any
  checkpointer: BaseCheckpointSaver | None
  chat_store: ChatStore
  executions: ExecutionRegistry
  lifecycle: ApplicationLifecycle
  threads: ThreadService
  runs: RunService


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
) -> AsyncIterator[Runtime]:
  """使用项目 Agent 工厂装配工具、审批和 Runtime，并管理资源生命周期。"""
  app_config = config if config is not None else load_app_config()
  async with (
    open_chat_store(Path(app_config.database.path).expanduser()) as store,
    make_checkpointer(app_config) as checkpointer,
  ):
    executions = ExecutionRegistry()
    ingestor = RunEventIngestor(store, executions)
    registry = create_builtin_registry()
    registry.register_many(await load_mcp_tools(app_config.mcp))
    agent = await create_lead_agent(
      config=app_config,
      tool_registry=registry,
      middlewares=[build_approval_middleware(registry.names)],
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
