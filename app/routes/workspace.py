"""工作目录资源查询不经过 Run、Graph 或工具执行入口。"""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request
from shikigen.runtime.workspace_resources import ResourceError
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse, Response

router = APIRouter(prefix="/api/workspace", tags=["Workspace"])
HEADERS = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}


async def _resource_query(perform_query, *arguments):
  try:
    return await run_in_threadpool(perform_query, *arguments)
  except ResourceError as error:
    raise HTTPException(error.status, str(error), headers=HEADERS) from error


@router.get(
  "",
  summary="获取工作区信息",
  description="获取当前工作目录的基本信息与唯一标识，用于校验宿主工作区状态及与后端的连接一致性。",
  response_description="当前工作区标识（workspace_id）及根目录绝对路径",
)
async def get_workspace(request: Request):
  workspace_identity = await _resource_query(
    request.app.state.runtime.resources.describe_workspace
  )
  return JSONResponse({"data": workspace_identity}, headers=HEADERS)


@router.get(
  "/resources/resolve",
  summary="解析工作区资源元数据",
  description=(
    "根据本地相对路径、绝对路径或 file:// URI 解析工作区内的文件，"
    "校验沙箱边界并生成绑定版本快照与预览标识。"
  ),
  response_description=(
    "已解析资源的元数据，包含 resource_id、相对/绝对路径、MIME 类型、"
    "大小、修改时间及是否支持预览等"
  ),
)
async def resolve_resource(request: Request, path: Annotated[str, Query(min_length=1)]):
  if (
    set(request.query_params) != {"path"}
    or len(request.query_params.getlist("path")) != 1
  ):
    raise HTTPException(422, "只接受一个 path 引用", headers=HEADERS)
  resource = await _resource_query(
    request.app.state.runtime.resources.resolve_resource, path
  )
  return JSONResponse({"data": resource}, headers=HEADERS)


@router.get(
  "/resources/{resource_id}/image",
  summary="获取工作区图片资源预览",
  description=(
    "根据已解析的资源标识 resource_id 获取图片二进制流；"
    "支持版本一致性校验（409）、20MiB 大小限制与 SVG 安全校验。"
  ),
  response_description="图片二进制数据流（附带对应 media_type 响应头）",
)
async def get_resource_image(request: Request, resource_id: str):
  image_bytes, mime = await _resource_query(
    request.app.state.runtime.resources.read_image, resource_id
  )
  return Response(image_bytes, media_type=mime, headers=HEADERS)
