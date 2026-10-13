"""可持久化的工具定义；执行由已登记的适配器负责。"""

from datetime import datetime
from typing import Annotated, Literal
from urllib.parse import urlsplit

from jsonschema import Draft7Validator
from jsonschema.exceptions import SchemaError
from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator

ToolName = Annotated[
  str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
]


def empty_input_schema() -> dict[str, JsonValue]:
  return {"type": "object", "properties": {}, "additionalProperties": False}


class ToolDefinition(BaseModel):
  model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

  id: str
  kind: str
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
    if value.get("$schema", "http://json-schema.org/draft-07/schema#") not in (
      "http://json-schema.org/draft-07/schema#",
      "https://json-schema.org/draft-07/schema#",
    ):
      raise ValueError("Only draft-07 schemas are supported")
    if info.field_name == "input_schema" and value.get("type") != "object":
      raise ValueError("Tool inputs must use an object schema")

    def check_refs(node):
      if isinstance(node, dict):
        for key, item in node.items():
          if key == "$ref" and (not isinstance(item, str) or not item.startswith("#")):
            raise ValueError("Only local schema references are supported")
          check_refs(item)
      elif isinstance(node, list):
        for item in node:
          check_refs(item)

    check_refs(value)
    try:
      Draft7Validator.check_schema(value)
    except SchemaError as error:
      raise ValueError(f"Invalid JSON schema: {error.message}") from None

    # Validate local pointers up front instead of accepting a schema that cannot
    # be resolved at execution. Network/anchor resolution is outside this slice.
    def resolve_refs(node):
      if isinstance(node, dict):
        ref = node.get("$ref")
        if ref is not None:
          if ref != "#" and not ref.startswith("#/"):
            raise ValueError("Only local JSON Pointer references are supported")
          target = value
          try:
            for segment in ref[2:].split("/") if ref != "#" else []:
              key = segment.replace("~1", "/").replace("~0", "~")
              target = target[int(key)] if isinstance(target, list) else target[key]
          except (KeyError, IndexError, TypeError, ValueError):
            raise ValueError("Unresolved local schema reference") from None
        for item in node.values():
          resolve_refs(item)
      elif isinstance(node, list):
        for item in node:
          resolve_refs(item)

    resolve_refs(value)
    return value


class HttpToolDefinition(ToolDefinition):
  kind: Literal["http"] = "http"
  method: Literal["GET"] = "GET"
  url: str

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


class PythonToolDefinition(ToolDefinition):
  kind: Literal["python"] = "python"
  code_path: str = Field(min_length=1)


class McpToolDefinition(ToolDefinition):
  kind: Literal["mcp"] = "mcp"
  server_id: str = Field(min_length=1)
  remote_name: str = Field(min_length=1)


AnyToolDefinition = Annotated[
  HttpToolDefinition | PythonToolDefinition | McpToolDefinition,
  Field(discriminator="kind"),
]


class ToolLibraryConfig(BaseModel):
  model_config = ConfigDict(extra="forbid")

  tools: list[AnyToolDefinition] = Field(default_factory=list)
  mcp_connections: dict[str, JsonValue] = Field(default_factory=dict)
