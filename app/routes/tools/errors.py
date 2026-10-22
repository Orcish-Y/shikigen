from fastapi import HTTPException
from shikigen.contracts.python_source import PythonSourceError
from shikigen.runtime.tool_library import ToolLibraryError
from shikigen.tools.http.openapi_import import OpenApiImportError


def fail(error: ToolLibraryError | PythonSourceError | OpenApiImportError):
  raise HTTPException(
    error.status, {"code": error.code, "message": str(error)}
  ) from None
