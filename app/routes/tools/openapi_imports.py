import asyncio

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field
from shikigen.runtime.tool_library import ToolLibraryError
from shikigen.tools.http.openapi_import import OpenApiImportError, preview_openapi

from app.routes.tools.errors import fail

router = APIRouter(prefix="/api/tools/openapi", tags=["tools"])


class OpenApiDocument(BaseModel):
  model_config = ConfigDict(extra="forbid", strict=True)
  document: str = Field(min_length=1, max_length=2_000_000)


class OpenApiSelection(BaseModel):
  model_config = ConfigDict(extra="forbid", strict=True)
  operation_key: str
  definition: dict
  security_option: str | None = None


class OpenApiImport(OpenApiDocument):
  tools: list[OpenApiSelection]
  version: str


@router.post("/preview")
async def preview(payload: OpenApiDocument, request: Request):
  try:
    _, version = await request.app.state.runtime.tools.list_tools()
    return {
      "data": await asyncio.to_thread(preview_openapi, payload.document),
      "version": version,
    }
  except (OpenApiImportError, ToolLibraryError) as error:
    fail(error)


@router.post("/imports", status_code=201)
async def import_tools(payload: OpenApiImport, request: Request):
  try:
    data = await request.app.state.runtime.lifecycle.accept(
      request.app.state.runtime.tools.import_openapi_tools(
        payload.document, [item.model_dump() for item in payload.tools], payload.version
      )
    )
    return {"data": data}
  except (OpenApiImportError, ToolLibraryError) as error:
    fail(error)
