"""可持久化的工具定义；执行由已登记的适配器负责。"""

from datetime import datetime
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import (
  BaseModel,
  ConfigDict,
  Field,
  JsonValue,
  field_validator,
  model_validator,
)

from shikigen.contracts.mcp_connections import AnyMcpConnection

ToolName = Annotated[
  str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
]


def empty_input_schema() -> dict[str, JsonValue]:
  return {"type": "object", "properties": {}, "additionalProperties": False}


class ToolDefinition[ToolKindT: str](BaseModel):
  model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

  id: str
  kind: ToolKindT
  display_name: str = Field(min_length=1)
  name: ToolName
  description: str = ""
  input_schema: dict[str, JsonValue] = Field(default_factory=empty_input_schema)
  output_schema: dict[str, JsonValue] | None = None
  enabled: bool = True
  timeout_seconds: float = Field(default=30, ge=1, le=300)
  created_at: datetime
  updated_at: datetime

  @field_validator("input_schema", "output_schema")
  @classmethod
  def validate_schema(cls, value, info):
    if value is None:
      return value
    from shikigen.contracts.input_schema import validate_tool_schema

    validate_tool_schema(value, inputs=info.field_name == "input_schema")
    return value


class HttpParameterMapping(BaseModel):
  model_config = ConfigDict(extra="forbid", strict=True)

  location: Literal["path", "query", "headers"]
  input_name: str = Field(min_length=1)
  name: str = Field(min_length=1)
  style: Literal["simple", "form"] | None = None
  explode: bool | None = None


class HttpAuthBinding(BaseModel):
  model_config = ConfigDict(extra="forbid", strict=True)

  id: ToolName
  kind: Literal["bearer", "api_key"]
  location: Literal["headers", "query"] = "headers"
  name: str = Field(default="Authorization", min_length=1)
  value: str = Field(default="", repr=False)


class HttpToolDefinition(ToolDefinition[Literal["http"]]):
  kind: Literal["http"] = "http"
  method: Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"] = "GET"
  url: str
  headers: dict[str, str] = Field(default_factory=dict)
  parameters: list[HttpParameterMapping] = Field(default_factory=list)
  auth: list[HttpAuthBinding] = Field(default_factory=list)

  @field_validator("url")
  @classmethod
  def validate_url(cls, value: str) -> str:
    try:
      parsed = urlsplit(value)
      port = parsed.port
    except ValueError:
      raise ValueError("Invalid HTTP URL") from None
    if (
      parsed.scheme not in ("http", "https")
      or not parsed.hostname
      or parsed.username is not None
      or parsed.password is not None
      or parsed.fragment
      or any(character.isspace() for character in value)
      or (port is not None and port < 1)
    ):
      raise ValueError("Use an absolute HTTP(S) URL without credentials or fragment")
    return value

  @model_validator(mode="after")
  def validate_request(self):
    from shikigen.contracts.http_requests import validate_http_request

    validate_http_request(self)
    return self


class PythonToolDefinition(ToolDefinition[Literal["python"]]):
  kind: Literal["python"] = "python"
  code_path: str = Field(min_length=1)


class McpToolDefinition(ToolDefinition[Literal["mcp"]]):
  kind: Literal["mcp"] = "mcp"
  connection_id: str = Field(min_length=1)
  remote_name: str = Field(min_length=1)
  source_tool: dict[str, JsonValue] = Field(default_factory=dict)


AnyToolDefinition = Annotated[
  HttpToolDefinition | PythonToolDefinition | McpToolDefinition,
  Field(discriminator="kind"),
]


class ToolLibraryConfig(BaseModel):
  model_config = ConfigDict(extra="forbid")

  tools: list[AnyToolDefinition] = Field(default_factory=list)
  mcp_connections: dict[str, AnyMcpConnection] = Field(default_factory=dict)

  @model_validator(mode="after")
  def validate_mcp_identities(self):
    if any(key != connection.id for key, connection in self.mcp_connections.items()):
      raise ValueError("MCP connection key must match its stable ID")
    sources = [
      (tool.connection_id, tool.remote_name)
      for tool in self.tools
      if tool.kind == "mcp"
    ]
    if len(set(sources)) != len(sources):
      raise ValueError("Duplicate MCP source identity")
    return self
