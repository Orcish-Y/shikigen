"""每个操作独立持有 MCP 会话；提供者负责进程/会话的获取与释放。"""

import asyncio
import json
import os
from collections.abc import AsyncGenerator
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
from pathlib import Path
from typing import Protocol

import httpx
import mcp
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client

from shikigen.contracts.mcp_connections import AnyMcpConnection
from shikigen.tool_execution.mcp.http import McpHttpClient, McpHttpClientSession

MCP_RESULT_LIMIT = 1024 * 1024


class McpSessionProvider(Protocol):
  def open_mcp_session(
    self, connection: AnyMcpConnection
  ) -> AbstractAsyncContextManager[mcp.ClientSession]: ...


class McpConnectionSessionProvider:
  def __init__(self, base_directory: Path):
    self.base_directory = base_directory

  @asynccontextmanager
  async def open_mcp_session(
    self, connection: AnyMcpConnection
  ) -> AsyncGenerator[mcp.ClientSession]:
    operation_error: BaseException | None = None
    session_error: Exception | None = None
    owner_task = asyncio.current_task()
    operation_finished = False

    def record_session_error(error: Exception):
      nonlocal session_error
      if (
        session_error is None
        and not operation_finished
        and (owner_task is None or owner_task.cancelling() == 0)
      ):
        session_error = error
        if owner_task is not None:
          owner_task.cancel()

    async def handle_message(message: object):
      if isinstance(message, Exception):
        # 默认 SDK handler 忽略解析错误，无法唤醒当前等待的请求。
        record_session_error(message)

    try:
      async with AsyncExitStack() as stack:
        if connection.transport == "stdio":
          # stderr 是服务调试通道，不混入协议/业务结果或应用日志。
          errlog = stack.enter_context(open(os.devnull, mode="w", encoding="utf-8"))
          parameters = mcp.StdioServerParameters(
            command=connection.command,
            args=connection.args,
            env=connection.env,
            cwd=str(self.base_directory / connection.cwd) if connection.cwd else None,
          )
          reader, writer = await stack.enter_async_context(
            stdio_client(parameters, errlog=errlog)
          )
        else:
          client = await stack.enter_async_context(
            McpHttpClient(headers=connection.headers, on_error=record_session_error)
          )
          reader, writer, _ = await stack.enter_async_context(
            streamable_http_client(connection.url, http_client=client)
          )
        prepared_mcp_session = (
          mcp.ClientSession(reader, writer)
          if connection.transport == "stdio"
          else McpHttpClientSession(
            reader, writer, message_handler=handle_message, http_client=client
          )
        )
        async with prepared_mcp_session as mcp_session:
          try:
            yield mcp_session
          except BaseException as error:
            # SDK 清理可能覆盖调用方取消；释放后传播原操作异常。
            operation_error = error
          finally:
            # 取消/完成之后收到的迟到响应不改写本次结果。
            operation_finished = True
    except BaseException as cleanup_error:
      if session_error is not None:
        operation_error = session_error
      elif operation_error is None or (
        isinstance(operation_error, asyncio.CancelledError)
        and isinstance(cleanup_error, Exception)
        and mcp_exception_code(cleanup_error) in ("mcp_transport", "mcp_authentication")
      ):
        # 传输子任务失败会取消等待方；此时传播真正的 HTTP 错误。
        raise
    finally:
      if session_error is not None and owner_task is not None:
        # 撤销由本提供者发出的那一次取消，不改变外部取消计数。
        owner_task.uncancel()
    if session_error is not None:
      raise session_error
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


def mcp_exception_code(error: Exception) -> str:
  if isinstance(error, BaseExceptionGroup):
    codes = {
      mcp_exception_code(child)
      for child in error.exceptions
      if isinstance(child, Exception)
    }
    for code in ("mcp_authentication", "mcp_transport"):
      if code in codes:
        return code
  if isinstance(error, httpx.HTTPStatusError):
    return (
      "mcp_authentication"
      if error.response.status_code in (401, 403)
      else "mcp_transport"
    )
  if isinstance(error, (httpx.TransportError, OSError)):
    return "mcp_transport"
  return "mcp_protocol"
