"""工具库管理的本地 MCP 连接，与启动自动加载配置独立。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class McpStdioSettings(BaseModel):
  model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

  display_name: str = Field(min_length=1)
  transport: Literal["stdio"] = "stdio"
  command: str = Field(min_length=1)
  args: list[str] = Field(default_factory=list)
  env: dict[str, str] = Field(default_factory=dict)
  cwd: str | None = None
  test_timeout_seconds: float = Field(default=30, ge=1, le=300)
  discovery_timeout_seconds: float = Field(default=30, ge=1, le=300)

  @field_validator("cwd", mode="before")
  @classmethod
  def empty_directory(cls, value):
    return None if value == "" else value

  @field_validator("display_name", "command", "cwd")
  @classmethod
  def nonempty_text(cls, value):
    if value is not None and (not value.strip() or "\0" in value):
      raise ValueError("Use nonempty text without NUL")
    return value

  @field_validator("args", "env")
  @classmethod
  def process_strings(cls, value):
    strings = value if isinstance(value, list) else [*value, *value.values()]
    if any("\0" in item for item in strings):
      raise ValueError("Process configuration cannot contain NUL")
    if isinstance(value, dict) and any(not key or "=" in key for key in value):
      raise ValueError("Environment variable names cannot be empty or contain =")
    return value


class McpStdioConnection(McpStdioSettings):
  id: str = Field(min_length=1)
  created_at: datetime
  updated_at: datetime
