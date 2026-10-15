"""HTTP 请求契约：映射不声明类型，所有业务约束从 input_schema 读取。"""

import re
from typing import Any, cast
from urllib.parse import parse_qsl, urlsplit

from shikigen.contracts.schema_references import resolve_schema
from shikigen.contracts.tool_definitions import HttpToolDefinition

SCALAR_TYPES = {"string", "integer", "number", "boolean"}
HEADER_NAME = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
TRANSPORT_HEADERS = {"content-length", "transfer-encoding", "host", "connection"}


def check_header(name: str, value: str | None = None):
  if not HEADER_NAME.fullmatch(name) or name.lower() in TRANSPORT_HEADERS:
    raise ValueError(f"Unsupported HTTP header name: {name}")
  if value is not None and any(ord(char) < 32 or ord(char) > 126 for char in value):
    raise ValueError(f"HTTP header {name} must contain printable ASCII characters")


def schema_types(node):
  value = node.get("type") if isinstance(node, dict) else None
  return set(value) if isinstance(value, list) else {value}


def validate_http_request(definition: HttpToolDefinition):
  root = cast(dict[str, Any], definition.input_schema)
  if "$ref" in root:
    raise ValueError("HTTP input root must declare its groups directly")
  properties = root.get("properties", {})
  if set(properties) - {"path", "query", "headers", "body"}:
    raise ValueError("HTTP inputs support only path/query/headers/body groups")
  if set(root.get("required", [])) - set(properties):
    raise ValueError("Required HTTP groups must be declared in properties")
  parsed = urlsplit(definition.url)
  if "{" in parsed.netloc + parsed.query or "}" in parsed.netloc + parsed.query:
    raise ValueError("URL placeholders are supported only in the path")
  placeholders = re.findall(r"\{([^{}]+)\}", parsed.path)
  if re.search(r"[{}]", re.sub(r"\{[^{}]+\}", "", parsed.path)):
    raise ValueError("Malformed URL path placeholder")
  for name, value in definition.headers.items():
    check_header(name, value)
  fixed_headers = {name.lower(): value for name, value in definition.headers.items()}
  if len(fixed_headers) != len(definition.headers):
    raise ValueError("Duplicate fixed HTTP headers")
  if (
    "body" in properties
    and fixed_headers.get("content-type", "application/json").lower()
    != "application/json"
  ):
    raise ValueError("Only application/json request bodies are supported")
  auth_targets = set()
  auth_ids = set()
  fixed_query = {name for name, _ in parse_qsl(parsed.query, keep_blank_values=True)}
  for binding in definition.auth:
    target = (
      binding.location,
      binding.name.lower() if binding.location == "headers" else binding.name,
    )
    if binding.id in auth_ids or target in auth_targets:
      raise ValueError("Duplicate authentication binding or target")
    auth_ids.add(binding.id)
    auth_targets.add(target)
    if binding.kind == "bearer" and target != ("headers", "authorization"):
      raise ValueError("Bearer authentication requires the Authorization header")
    if binding.location == "headers":
      check_header(binding.name, binding.value)
      if target[1] in fixed_headers or target[1] == "content-type":
        raise ValueError("Authentication conflicts with a fixed or Content-Type header")
    elif binding.name in fixed_query:
      raise ValueError("Authentication conflicts with a URL query parameter")
  targets, sources = set(), set()
  path_targets = set()
  for mapping in definition.parameters:
    target = (
      mapping.location,
      mapping.name.lower() if mapping.location == "headers" else mapping.name,
    )
    source = (mapping.location, mapping.input_name)
    if target in auth_targets:
      raise ValueError("Authentication conflicts with a business parameter mapping")
    if target in targets or source in sources:
      raise ValueError(
        f"Duplicate parameter target or input: {mapping.location}.{mapping.input_name}"
      )
    targets.add(target)
    sources.add(source)
    expected_style = "form" if mapping.location == "query" else "simple"
    if mapping.style not in (None, expected_style):
      raise ValueError(
        f"{mapping.location} supports only {expected_style} serialization"
      )
    if mapping.location == "headers":
      check_header(mapping.name)
      if (
        mapping.name.lower() in fixed_headers or mapping.name.lower() == "content-type"
      ):
        raise ValueError(
          "Mapped headers cannot overwrite fixed headers or Content-Type"
        )
    group = resolve_schema(root, properties.get(mapping.location))
    if not isinstance(group, dict) or group.get("type") != "object":
      raise ValueError(f"Declare an object schema for {mapping.location}")
    node = resolve_schema(root, group.get("properties", {}).get(mapping.input_name))
    types = schema_types(node) - {"null"}
    if mapping.location == "query" and types == {"array"}:
      items = resolve_schema(root, node.get("items"))
      if not schema_types(items) <= SCALAR_TYPES:
        raise ValueError("Query arrays support only non-null scalar items")
    elif not types or not types <= SCALAR_TYPES:
      raise ValueError(
        f"{mapping.location}.{mapping.input_name} requires a scalar schema"
      )
    if mapping.location == "path":
      path_targets.add(mapping.name)
      if mapping.location not in root.get(
        "required", []
      ) or mapping.input_name not in group.get("required", []):
        raise ValueError("Path parameters and their group must be required")
      if "null" in schema_types(node):
        raise ValueError("Path parameters cannot declare null")
  if path_targets != set(placeholders):
    raise ValueError("URL placeholders must match required path parameter mappings")
  for location in ("path", "query", "headers"):
    if location not in properties:
      continue
    group = resolve_schema(root, properties[location])
    if not isinstance(group, dict) or group.get("type") != "object":
      raise ValueError(f"{location} must be an object schema")
    if set(group.get("required", [])) - set(group.get("properties", {})):
      raise ValueError(f"Required {location} fields must be declared")
    declared = {(location, name) for name in group.get("properties", {})}
    if declared != {source for source in sources if source[0] == location}:
      raise ValueError(f"Every {location} field must have exactly one mapping")
