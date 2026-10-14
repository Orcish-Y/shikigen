from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, JsonValue
from shikigen.contracts.tool_definitions import HttpToolDefinition
from shikigen.runtime.tool_library import ToolLibraryError

router = APIRouter(prefix="/api/tools", tags=["tools"])


def fail(error: ToolLibraryError):
  raise HTTPException(
    error.status, {"code": error.code, "message": str(error)}
  ) from None


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
    "enabled": "启用",
    "timeout_seconds": "超时（秒）",
    "input_schema": "输入结构",
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


@router.get("/validate-name")
async def validate_name(
  request: Request, response: Response, name: str, tool_id: str | None = None
):
  response.headers["Cache-Control"] = "no-store"
  try:
    return {"data": await request.app.state.runtime.tools.validate_name(name, tool_id)}
  except ToolLibraryError as error:
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
  except ToolLibraryError as error:
    fail(error)


@router.get("/{tool_id}")
async def get_tool(tool_id: str, request: Request, response: Response):
  response.headers["Cache-Control"] = "no-store"
  try:
    tool, version = await request.app.state.runtime.tools.get_tool(tool_id)
    return {"data": tool, "version": version}
  except ToolLibraryError as error:
    fail(error)


@router.post("", status_code=201)
async def create_tool(payload: dict, request: Request):
  try:
    # Preserve omitted-kind creates from the first HTTP API slice at its boundary.
    definition = {"kind": "http", **payload}
    tool, version = await request.app.state.runtime.lifecycle.accept(
      request.app.state.runtime.tools.save_tool(definition)
    )
    return {"data": tool, "version": version}
  except ToolLibraryError as error:
    fail(error)


class ToolUpdate(BaseModel):
  model_config = ConfigDict(extra="forbid")
  definition: dict
  version: str


@router.put("/{tool_id}")
async def update_tool(tool_id: str, payload: ToolUpdate, request: Request):
  try:
    tool, version = await request.app.state.runtime.lifecycle.accept(
      request.app.state.runtime.tools.save_tool(
        payload.definition, tool_id=tool_id, version=payload.version
      )
    )
    return {"data": tool, "version": version}
  except ToolLibraryError as error:
    fail(error)


class ToolInputs(BaseModel):
  model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
  inputs: dict[str, JsonValue]


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
  except ToolLibraryError as error:
    fail(error)


@router.get("/tests/{test_id}")
async def get_test(test_id: str, request: Request, response: Response):
  response.headers["Cache-Control"] = "no-store"
  try:
    return {"data": request.app.state.runtime.tools.get_test(test_id)}
  except ToolLibraryError as error:
    fail(error)
