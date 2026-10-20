"""工具库管理的 MCP 连接，与启动自动加载配置独立。"""

from datetime import datetime
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Discriminator, Field, Tag, field_validator


class McpConnectionSettings(BaseModel):
  model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

  display_name: str = Field(min_length=1)
  test_timeout_seconds: float = Field(default=30, ge=1, le=300)
  discovery_timeout_seconds: float = Field(default=30, ge=1, le=300)

  @field_validator("display_name")
  @classmethod
  def nonempty_name(cls, value):
    if not value.strip() or "\0" in value:
      raise ValueError("Use nonempty text without NUL")
    return value


class McpStdioSettings(McpConnectionSettings):
  transport: Literal["stdio"] = "stdio"
  command: str = Field(min_length=1)
  args: list[str] = Field(default_factory=list)
  env: dict[str, str] = Field(default_factory=dict)
  cwd: str | None = None

  @field_validator("cwd", mode="before")
  @classmethod
  def empty_directory(cls, value):
    return None if value == "" else value

  @field_validator("command", "cwd")
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


class McpStreamableHttpSettings(McpConnectionSettings):
  transport: Literal["streamable_http"] = "streamable_http"
  url: str = Field(min_length=1)
  headers: dict[str, str] = Field(default_factory=dict)

  @field_validator("url")
  @classmethod
  def http_endpoint(cls, value):
    parsed = urlsplit(value)
    if (
      parsed.scheme not in ("http", "https")
      or not parsed.hostname
      or parsed.username is not None
      or parsed.password is not None
      or parsed.fragment
      or any(char.isspace() or ord(char) < 32 for char in value)
    ):
      raise ValueError("Use an HTTP(S) MCP endpoint without userinfo or fragment")
    # urlsplit 只在访问 port 时检查端口格式和范围。
    _ = parsed.port
    return value

  @field_validator("headers")
  @classmethod
  def http_headers(cls, value):
    from shikigen.contracts.http_requests import check_header

    reserved = {
      "accept",
      "content-type",
      "mcp-session-id",
      "mcp-protocol-version",
      "last-event-id",
    }
    names = set()
    for name, content in value.items():
      check_header(name, content)
      lowered = name.lower()
      if lowered in names or lowered in reserved:
        raise ValueError("Duplicate or protocol-managed MCP header")
      names.add(lowered)
    return value


class McpStreamableHttpConnection(McpStreamableHttpSettings):
  id: str = Field(min_length=1)
  created_at: datetime
  updated_at: datetime


def connection_transport(value):
  # 原 stdio 配置允许省略默认 transport；选择分支时兼容，不改变输入值。
  return (
    value.get("transport", "stdio")
    if isinstance(value, dict)
    else getattr(value, "transport", None)
  )


AnyMcpConnection = Annotated[
  Annotated[McpStdioConnection, Tag("stdio")]
  | Annotated[McpStreamableHttpConnection, Tag("streamable_http")],
  Discriminator(connection_transport),
]

AnyMcpSettings = Annotated[
  McpStdioSettings | McpStreamableHttpSettings, Field(discriminator="transport")
]
