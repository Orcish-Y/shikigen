from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict, JsonValue
from shikigen.contracts.python_source import PythonSourceError
from shikigen.contracts.tool_definitions import (
  HttpToolDefinition,
  McpToolDefinition,
  PythonToolDefinition,
)
from shikigen.tools.tool_library import ToolLibraryError

from app.routes.tools.errors import fail

router = APIRouter(prefix="/api/tools", tags=["tools"])


@router.get("/schema/http")
async def parameters_schema():
  schema = HttpToolDefinition.model_json_schema()
  schema["title"] = "基本信息与请求配置"
  for field in ("id", "created_at", "updated_at"):
    del schema["properties"][field]
  schema["required"] = [
    field
    for field in schema["required"]
    if field not in ("id", "created_at", "updated_at")
  ]
  titles = {
    "display_name": "页面名称",
    "name": "调用名称",
    "description": "说明",
    "kind": "工具类型",
    "method": "请求方法",
    "url": "请求地址",
    "headers": "固定请求头",
    "parameters": "请求映射",
    "auth": "认证",
    "enabled": "启用",
    "timeout_seconds": "超时（秒）",
    "input_schema": "输入结构",
    "output_schema": "输出结构（可选）",
    "openapi_source": "OpenAPI 原始来源",
  }
  for field, title in titles.items():
    schema["properties"][field]["title"] = title
  schema["properties"]["input_schema"] = {
    "type": "object",
    "title": titles["input_schema"],
  }
  schema["properties"]["output_schema"] = {
    "type": ["object", "null"],
    "title": titles["output_schema"],
  }
  return {"data": schema}


@router.get("/schema/python")
async def python_parameters_schema():
  schema = PythonToolDefinition.model_json_schema()
  for field in ("id", "created_at", "updated_at", "code_path"):
    del schema["properties"][field]
  schema["required"] = [
    field for field in schema["required"] if field in schema["properties"]
  ] + ["source"]
  schema["properties"]["source"] = {
    "type": "string",
    "minLength": 1,
    "title": "Python 源码",
  }
  titles = {
    "display_name": "页面名称",
    "name": "调用名称",
    "description": "说明",
    "kind": "工具类型",
    "enabled": "启用",
    "timeout_seconds": "超时（秒）",
    "input_schema": "源码参数与类型补齐",
    "output_schema": "输出结构（可选）",
  }
  for field, title in titles.items():
    schema["properties"][field]["title"] = title
  schema["properties"]["input_schema"] = {
    "type": "object",
    "title": titles["input_schema"],
  }
  schema["properties"]["output_schema"] = {
    "type": ["object", "null"],
    "title": titles["output_schema"],
  }
  return {"data": schema}


@router.get("/schema/mcp")
async def mcp_parameters_schema():
  schema = McpToolDefinition.model_json_schema()
  for field in ("id", "created_at", "updated_at"):
    del schema["properties"][field]
  schema["required"] = [
    field for field in schema["required"] if field in schema["properties"]
  ]
  titles = {
    "display_name": "页面名称",
    "name": "调用名称",
    "description": "说明",
    "enabled": "启用",
    "timeout_seconds": "超时（秒）",
    "connection_id": "所属连接",
    "remote_name": "远端工具名",
    "source_tool": "完整来源",
    "input_schema": "输入结构",
    "output_schema": "输出结构（可选）",
  }
  for field, title in titles.items():
    schema["properties"][field]["title"] = title
  for field in (
    "connection_id",
    "remote_name",
    "source_tool",
    "input_schema",
    "output_schema",
  ):
    schema["properties"][field]["readOnly"] = True
  schema["properties"]["input_schema"] = {
    "type": "object",
    "title": "输入结构",
    "readOnly": True,
  }
  schema["properties"]["output_schema"] = {
    "type": ["object", "null"],
    "title": "输出结构（可选）",
    "readOnly": True,
  }
  return {"data": schema}


@router.get("/validate-name")
async def validate_name(
  request: Request, response: Response, name: str, tool_id: str | None = None
):
  response.headers["Cache-Control"] = "no-store"
  try:
    return {"data": await request.app.state.runtime.tools.validate_name(name, tool_id)}
  except (ToolLibraryError, PythonSourceError) as error:
    fail(error)


@router.get("")
async def list_tools(request: Request, response: Response):
  response.headers["Cache-Control"] = "no-store"
  try:
    tools, version = await request.app.state.runtime.tools.list_tools()
    return {
      "data": tools,
      "version": version,
      "reserved_names": request.app.state.runtime.tools.reserved_names,
    }
  except (ToolLibraryError, PythonSourceError) as error:
    fail(error)


@router.get("/{tool_id}")
async def get_tool(tool_id: str, request: Request, response: Response):
  response.headers["Cache-Control"] = "no-store"
  try:
    tool, version = await request.app.state.runtime.tools.get_tool_detail(tool_id)
    return {"data": tool, "version": version}
  except (ToolLibraryError, PythonSourceError) as error:
    fail(error)


@router.post("", status_code=201)
async def create_tool(payload: dict, request: Request):
  try:
    # Preserve omitted-kind creates from the first HTTP API slice at its boundary.
    definition = {"kind": "http", **payload}
    tool, _ = await request.app.state.runtime.lifecycle.accept(
      request.app.state.runtime.tools.save_tool(definition)
    )
    return {"data": {"id": tool.id}}
  except (ToolLibraryError, PythonSourceError) as error:
    fail(error)


class ToolUpdate(BaseModel):
  model_config = ConfigDict(extra="forbid")
  definition: dict
  version: str


class ToolDelete(BaseModel):
  model_config = ConfigDict(extra="forbid", strict=True)
  version: str


@router.delete("/{tool_id}", status_code=204)
async def delete_tool(tool_id: str, payload: ToolDelete, request: Request):
  try:
    await request.app.state.runtime.lifecycle.accept(
      request.app.state.runtime.tools.delete_tool(tool_id, payload.version)
    )
    return Response(status_code=204)
  except (ToolLibraryError, PythonSourceError) as error:
    fail(error)


@router.put("/{tool_id}", status_code=204)
async def update_tool(tool_id: str, payload: ToolUpdate, request: Request):
  try:
    await request.app.state.runtime.lifecycle.accept(
      request.app.state.runtime.tools.save_tool(
        payload.definition,
        tool_id=tool_id,
        version=payload.version,
      )
    )
    return Response(status_code=204)
  except (ToolLibraryError, PythonSourceError) as error:
    fail(error)


class ToolInputs(BaseModel):
  model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
  inputs: dict[str, JsonValue]


class ToolDraftTest(ToolInputs):
  definition: dict
  tool_id: str | None = None


@router.post("/tests", status_code=202)
async def start_draft_test(payload: ToolDraftTest, request: Request):
  try:
    snapshot = await request.app.state.runtime.lifecycle.accept(
      request.app.state.runtime.tools.start_draft_test(
        payload.definition, payload.inputs, payload.tool_id
      )
    )
    return {"data": snapshot}
  except (ToolLibraryError, PythonSourceError) as error:
    fail(error)


@router.post("/{tool_id}/execute")
async def execute_tool(tool_id: str, payload: ToolInputs, request: Request):
  return {
    "data": await request.app.state.runtime.tools.execute_tool(tool_id, payload.inputs)
  }


@router.post("/{tool_id}/tests", status_code=202)
async def start_test(tool_id: str, payload: ToolInputs, request: Request):
  try:
    snapshot = await request.app.state.runtime.lifecycle.accept(
      request.app.state.runtime.tools.start_test(tool_id, payload.inputs)
    )
    return {"data": snapshot}
  except (ToolLibraryError, PythonSourceError) as error:
    fail(error)


@router.get("/tests/{test_id}")
async def get_test(test_id: str, request: Request, response: Response):
  response.headers["Cache-Control"] = "no-store"
  try:
    return {"data": request.app.state.runtime.tools.get_test(test_id)}
  except (ToolLibraryError, PythonSourceError) as error:
    fail(error)


@router.post("/tests/{test_id}/cancel")
async def cancel_test(test_id: str, request: Request):
  try:
    snapshot = await request.app.state.runtime.lifecycle.accept(
      request.app.state.runtime.tools.cancel_test(test_id)
    )
    return {"data": snapshot}
  except (ToolLibraryError, PythonSourceError) as error:
    fail(error)
