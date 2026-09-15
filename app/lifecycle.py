"""应用任务的接收、保留和关闭；不处理 Thread 或 Run 的业务规则。"""

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any

from shikigen.execution import ExecutionRegistry

logger = logging.getLogger(__name__)


class ApplicationLifecycle:
  def __init__(self, executions: ExecutionRegistry) -> None:
    self._executions = executions
    self._operations: set[asyncio.Task] = set()
    self._closing = False
    self._shutdown_task: asyncio.Task[None] | None = None

  async def accept[T](self, operation: Coroutine[Any, Any, T]) -> T:
    """接收后的创建操作由应用生命周期持有；调用方断开不打断提交与启动。"""
    if self._closing:
      operation.close()
      raise RuntimeError("Application is shutting down")
    task = asyncio.create_task(operation)
    self._operations.add(task)

    def finished(task: asyncio.Task) -> None:
      self._operations.discard(task)
      if not task.cancelled() and (error := task.exception()) is not None:
        logger.debug(
          "Application operation failed",
          exc_info=(type(error), error, error.__traceback__),
        )

    task.add_done_callback(finished)
    return await asyncio.shield(task)

  async def shutdown(self) -> None:
    """停止接收，等已接收的创建操作交接，再停止并回收执行资源。"""
    if self._shutdown_task is None:
      self._closing = True

      async def close() -> None:
        await asyncio.gather(*tuple(self._operations), return_exceptions=True)
        await self._executions.shutdown()

      self._shutdown_task = asyncio.create_task(close())
    # 关闭者被取消也要先收完资源，防止上下文提前关闭数据库。
    try:
      await asyncio.shield(self._shutdown_task)
    except asyncio.CancelledError:
      await self._shutdown_task
      raise
