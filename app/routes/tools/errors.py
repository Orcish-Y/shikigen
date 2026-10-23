from fastapi import HTTPException
from shikigen.contracts.python_source import PythonSourceError
from shikigen.tools.http.openapi_import import OpenApiImportError
from shikigen.tools.tool_library import ToolLibraryError


def fail(error: ToolLibraryError | PythonSourceError | OpenApiImportError):
  detail = {"code": error.code, "message": str(error)}
  if isinstance(error, ToolLibraryError) and error.resource_ids:
    detail["resource_ids"] = error.resource_ids
  raise HTTPException(error.status, detail) from None
