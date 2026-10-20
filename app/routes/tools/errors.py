from fastapi import HTTPException
from shikigen.contracts.python_source import PythonSourceError
from shikigen.runtime.tool_library import ToolLibraryError


def fail(error: ToolLibraryError | PythonSourceError):
  raise HTTPException(
    error.status, {"code": error.code, "message": str(error)}
  ) from None
