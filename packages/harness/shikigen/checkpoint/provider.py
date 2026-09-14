from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from shikigen.app_config import AppConfig, load_app_config


@asynccontextmanager
async def make_checkpointer(
  app_config: AppConfig | None = None,
) -> AsyncIterator[BaseCheckpointSaver]:
  """按配置创建 checkpoint 存储，由调用者的 async with 管理生命周期。

  未传配置时读取默认配置文件。每次进入都创建独立实例；sqlite 在退出
  （包括初始化或调用者异常）时关闭连接。调用者应先停止所有使用者再退出。
  """
  resolved_config = app_config if app_config is not None else load_app_config()
  config = resolved_config.checkpointer
  if config.type == "memory":
    yield InMemorySaver()
    return

  path = Path(config.path).expanduser()
  path.parent.mkdir(parents=True, exist_ok=True)
  async with AsyncSqliteSaver.from_conn_string(str(path)) as checkpointer:
    await checkpointer.setup()
    yield checkpointer
