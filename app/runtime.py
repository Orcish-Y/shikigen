"""运行时配置与已装配依赖的容器；业务操作和资源生命周期由对应模块负责。"""

from dataclasses import dataclass
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from shikigen.app_config import AppConfig
from shikigen.execution import ExecutionRegistry

from app.lifecycle import ApplicationLifecycle
from app.persistence import ChatStore
from app.services.run import RunService
from app.services.thread import ThreadService


@dataclass(frozen=True, slots=True)
class Runtime:
  config: AppConfig
  agent: Any
  checkpointer: BaseCheckpointSaver | None
  chat_store: ChatStore
  executions: ExecutionRegistry
  lifecycle: ApplicationLifecycle
  threads: ThreadService
  runs: RunService
