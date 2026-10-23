from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict
from shikigen.contracts.mcp_connections import (
  McpStdioSettings,
  McpStreamableHttpSettings,
)
from shikigen.tools.tool_library import ToolLibraryError

from app.routes.tools.errors import fail

router = APIRouter(prefix="/api/mcp")


@router.get("/schema/stdio")
async def stdio_schema():
  return {"data": connection_schema(McpStdioSettings)}


@router.get("/schema/streamable_http")
async def streamable_http_schema():
  return {"data": connection_schema(McpStreamableHttpSettings)}


def connection_schema(settings: type[McpStdioSettings | McpStreamableHttpSettings]):
  schema = settings.model_json_schema()
  schema.pop("title", None)
  titles = {
    "display_name": "连接名称",
    "command": "启动命令",
    "args": "启动参数",
    "env": "环境变量",
    "cwd": "工作目录（可选）",
    "url": "远程 MCP URL",
    "headers": "请求头",
    "test_timeout_seconds": "连接测试预算（秒）",
    "discovery_timeout_seconds": "工具发现预算（秒）",
  }
  for key, title in titles.items():
    if key in schema["properties"]:
      schema["properties"][key]["title"] = title
  return schema


@router.get("/connections")
async def list_connections(request: Request, response: Response):
  response.headers["Cache-Control"] = "no-store"
  try:
    data, version = await request.app.state.runtime.tools.list_mcp_connections()
    return {"data": data, "version": version}
  except ToolLibraryError as error:
    fail(error)


@router.get("/connections/{connection_id}")
async def get_connection(connection_id: str, request: Request, response: Response):
  response.headers["Cache-Control"] = "no-store"
  try:
    data, version = await request.app.state.runtime.tools.get_mcp_connection(
      connection_id
    )
    return {"data": data, "version": version}
  except ToolLibraryError as error:
    fail(error)


@router.post("/connections", status_code=201)
async def create_connection(payload: dict, request: Request):
  try:
    connection_id = await request.app.state.runtime.lifecycle.accept(
      request.app.state.runtime.tools.save_mcp_connection(payload)
    )
    return {"data": {"id": connection_id}}
  except ToolLibraryError as error:
    fail(error)


class ConnectionUpdate(BaseModel):
  model_config = ConfigDict(extra="forbid", strict=True)
  definition: dict
  version: str


class ConnectionDelete(BaseModel):
  model_config = ConfigDict(extra="forbid", strict=True)
  version: str


@router.delete("/connections/{connection_id}", status_code=204)
async def delete_connection(
  connection_id: str, payload: ConnectionDelete, request: Request
):
  try:
    await request.app.state.runtime.lifecycle.accept(
      request.app.state.runtime.tools.delete_mcp_connection(
        connection_id, payload.version
      )
    )
    return Response(status_code=204)
  except ToolLibraryError as error:
    fail(error)


@router.post("/connections/{connection_id}/test")
async def test_connection(connection_id: str, request: Request):
  try:
    data = await request.app.state.runtime.lifecycle.accept(
      request.app.state.runtime.tools.inspect_mcp_connection(
        connection_id, discover=False
      )
    )
    return {"data": data}
  except ToolLibraryError as error:
    fail(error)


@router.post("/connections/{connection_id}/discover")
async def discover_tools(connection_id: str, request: Request):
  try:
    data = await request.app.state.runtime.lifecycle.accept(
      request.app.state.runtime.tools.inspect_mcp_connection(
        connection_id, discover=True
      )
    )
    return {"data": data}
  except ToolLibraryError as error:
    fail(error)


class ToolSelection(BaseModel):
  model_config = ConfigDict(extra="forbid", strict=True)
  remote_name: str
  name: str


class DiscoveryImport(BaseModel):
  model_config = ConfigDict(extra="forbid", strict=True)
  discovery_id: str
  tools: list[ToolSelection]


@router.post("/connections/{connection_id}/imports")
async def import_tools(connection_id: str, payload: DiscoveryImport, request: Request):
  try:
    data = await request.app.state.runtime.lifecycle.accept(
      request.app.state.runtime.tools.import_mcp_tools(
        connection_id,
        payload.discovery_id,
        [tool.model_dump() for tool in payload.tools],
      )
    )
    return {"data": data}
  except ToolLibraryError as error:
    fail(error)


@router.put("/connections/{connection_id}", status_code=204)
async def update_connection(
  connection_id: str, payload: ConnectionUpdate, request: Request
):
  try:
    await request.app.state.runtime.lifecycle.accept(
      request.app.state.runtime.tools.save_mcp_connection(
        payload.definition, connection_id=connection_id, version=payload.version
      )
    )
    return Response(status_code=204)
  except ToolLibraryError as error:
    fail(error)
