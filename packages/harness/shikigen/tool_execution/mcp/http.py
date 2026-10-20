"""MCP HTTP 的有界会话终止与 SSE 断流诊断；协议解析仍交给 SDK。"""

import asyncio
from collections.abc import AsyncIterator, Callable
from contextvars import ContextVar
from dataclasses import dataclass, replace
from datetime import timedelta

import httpx
import mcp
from mcp.shared.message import ClientMessageMetadata, MessageMetadata
from mcp.shared.session import ProgressFnT
from pydantic import BaseModel


@dataclass(slots=True)
class McpSseResponseState:
  resumable: bool = False


class McpResponseStream(httpx.AsyncByteStream):
  def __init__(
    self,
    stream: httpx.AsyncByteStream,
    on_error: Callable[[Exception], None],
    state: McpSseResponseState,
  ):
    self.stream = stream
    self.on_error = on_error
    self.state = state

  async def __aiter__(self) -> AsyncIterator[bytes]:
    try:
      async for chunk in self.stream:
        yield chunk
    except httpx.TransportError as error:
      if not self.state.resumable:
        self.on_error(error)
      raise
    # SDK 收到完整的 SSE result/error 后主动关闭响应，不会继续读到 EOF。
    # 若仍在读取就遇到 EOF，默认 SDK 会吞掉断流并一直等到操作超时。
    if not self.state.resumable:
      error = httpx.RemoteProtocolError(
        "MCP SSE response ended before a JSON-RPC result"
      )
      self.on_error(error)
      raise error

  async def aclose(self) -> None:
    await self.stream.aclose()


class McpHttpClient(httpx.AsyncClient):
  def __init__(self, *, headers: dict[str, str], on_error: Callable[[Exception], None]):
    super().__init__(
      headers=headers,
      timeout=httpx.Timeout(300, connect=10),
      follow_redirects=False,
    )
    self.on_error = on_error
    self.sse_response: ContextVar[McpSseResponseState | None] = ContextVar(
      "mcp_sse_response", default=None
    )

  async def record_resumption_token(self, token: str):
    # SDK 在处理该 HTTP 响应的同一任务中回调；并发响应各有自己的状态。
    state = self.sse_response.get()
    if state is not None and token:
      state.resumable = True

  async def send(self, request: httpx.Request, **kwargs) -> httpx.Response:
    if request.method == "DELETE":
      # httpx.Timeout 只约束每阶段空闲时间，无法限制持续慢速返回的总耗时。
      async with asyncio.timeout(0.5):
        return await super().send(request, **kwargs)
    response = await super().send(request, **kwargs)
    if (
      request.method == "POST"
      and response.status_code == 200
      and response.headers.get("content-type", "")
      .lower()
      .startswith("text/event-stream")
      and isinstance(response.stream, httpx.AsyncByteStream)
    ):
      state = McpSseResponseState()
      self.sse_response.set(state)
      response.stream = McpResponseStream(response.stream, self.on_error, state)
    return response


class McpHttpClientSession(mcp.ClientSession):
  def __init__(self, *args, http_client: McpHttpClient, **kwargs):
    super().__init__(*args, **kwargs)
    self.http_client = http_client

  async def send_request[ResultT: BaseModel](
    self,
    request: mcp.types.ClientRequest,
    result_type: type[ResultT],
    request_read_timeout_seconds: timedelta | None = None,
    metadata: MessageMetadata = None,
    progress_callback: ProgressFnT | None = None,
  ) -> ResultT:
    if metadata is None or isinstance(metadata, ClientMessageMetadata):
      client_metadata = metadata or ClientMessageMetadata()
      previous_callback = client_metadata.on_resumption_token_update

      async def record_token(token: str):
        await self.http_client.record_resumption_token(token)
        if previous_callback is not None:
          await previous_callback(token)

      # 只观察 SDK 已解析的续读令牌，不自行解析 SSE 行或 JSON-RPC。
      metadata = replace(client_metadata, on_resumption_token_update=record_token)
    return await super().send_request(
      request, result_type, request_read_timeout_seconds, metadata, progress_callback
    )
