"""工具执行的公共结果契约，供协调器和类型适配器共同使用。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, JsonValue


class ToolResult(BaseModel):
  model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

  status: Literal["success", "error", "timeout", "cancelled"]
  data: JsonValue = None
  error: dict[str, JsonValue] | None = None
  duration_ms: float = 0
  details: dict[str, JsonValue] = {}


def failure(code: str, message: str, **kwargs) -> ToolResult:
  return ToolResult(status="error", error={"code": code, "message": message}, **kwargs)
