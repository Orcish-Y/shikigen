"""每个操作独立持有 MCP 会话；提供者负责进程/会话的获取与释放。"""

import json
import os
from collections.abc import AsyncGenerator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path
from typing import Protocol

import mcp
from mcp.client.stdio import stdio_client

from shikigen.contracts.mcp_connections import McpStdioConnection

MCP_RESULT_LIMIT = 1024 * 1024


class McpSessionProvider(Protocol):
  def open_mcp_session(
    self, connection: McpStdioConnection
  ) -> AbstractAsyncContextManager[mcp.ClientSession]: ...


class McpStdioSessionProvider:
  def __init__(self, base_directory: Path):
    self.base_directory = base_directory

  @asynccontextmanager
  async def open_mcp_session(
    self, connection: McpStdioConnection
  ) -> AsyncGenerator[mcp.ClientSession]:
    # stderr 是服务调试通道，不混入协议/业务结果或应用日志。
    with open(os.devnull, mode="w", encoding="utf-8") as errlog:
      parameters = mcp.StdioServerParameters(
        command=connection.command,
        args=connection.args,
        env=connection.env,
        cwd=str(self.base_directory / connection.cwd) if connection.cwd else None,
      )
      operation_error: BaseException | None = None
      try:
        async with stdio_client(parameters, errlog=errlog) as (reader, writer):
          async with mcp.ClientSession(reader, writer) as mcp_session:
            try:
              yield mcp_session
            except BaseException as error:
              # SDK 的 AnyIO 清理可能以 BrokenResourceError 覆盖调用方取消。
              # 先正常退出会话/进程上下文，释放完成后再传播原操作异常。
              operation_error = error
      except BaseException:
        if operation_error is None:
          raise
      if operation_error is not None:
        raise operation_error


async def list_mcp_session_tools(mcp_session: mcp.ClientSession) -> list[dict]:
  tools: list[dict] = []
  cursors: set[str] = set()
  cursor = None
  size = 0
  while True:
    page = await mcp_session.list_tools(
      params=mcp.types.PaginatedRequestParams(cursor=cursor)
    )
    for tool in page.tools:
      value = tool.model_dump(mode="json", by_alias=True, exclude_unset=True)
      size += len(json.dumps(value, ensure_ascii=False).encode("utf-8"))
      tools.append(value)
    if size > MCP_RESULT_LIMIT or len(tools) > 1000:
      raise ValueError("MCP discovery exceeds 1 MiB or 1000 tools")
    cursor = page.nextCursor
    if not cursor:
      break
    if cursor in cursors:
      raise ValueError("MCP discovery repeated a pagination cursor")
    cursors.add(cursor)
  names = [tool["name"] for tool in tools]
  if len(set(names)) != len(names):
    raise ValueError("MCP discovery returned duplicate remote tool names")
  return tools


def mcp_exception_message(error: Exception) -> str:
  if isinstance(error, BaseExceptionGroup):
    return "; ".join(
      mcp_exception_message(child)
      for child in error.exceptions
      if isinstance(child, Exception)
    )
  return str(error) or type(error).__name__
