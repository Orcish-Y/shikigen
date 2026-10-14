"""所有消费者共用的执行预算、校验、结果和按类型登记的适配器。"""

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from typing import Literal
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, JsonValue

from shikigen.contracts.http_requests import check_header
from shikigen.contracts.input_schema import get_schema_validator_class
from shikigen.contracts.tool_definitions import HttpToolDefinition, ToolDefinition

OUTPUT_LIMIT = 1024 * 1024


def reject_nonfinite(value: str):
  raise ValueError(f"Non-finite JSON value: {value}")


class ToolResult(BaseModel):
  model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

  status: Literal["success", "error", "timeout", "cancelled"]
  data: JsonValue = None
  error: dict[str, JsonValue] | None = None
  duration_ms: float = 0
  details: dict[str, JsonValue] = {}


def failure(code: str, message: str, **kwargs) -> ToolResult:
  return ToolResult(status="error", error={"code": code, "message": message}, **kwargs)


class HttpAdapter:
  async def execute(self, definition: ToolDefinition, inputs: dict) -> ToolResult:
    if not isinstance(definition, HttpToolDefinition):
      return failure("configuration", "Expected an HTTP tool definition")
    url = definition.url
    headers = dict(definition.headers)
    query: list[tuple[str, str]] = []
    if set(inputs) - {"path", "query", "headers", "body"}:
      return failure("input_validation", "Unexpected HTTP input group")
    for location in ("path", "query", "headers"):
      if location not in inputs:
        continue
      group = inputs[location]
      allowed = {
        item.input_name for item in definition.parameters if item.location == location
      }
      if not isinstance(group, dict) or set(group) - allowed:
        return failure(
          "input_validation", f"Unmapped {location} input", details={"path": [location]}
        )

    def scalar(value):
      if isinstance(value, bool):
        return "true" if value else "false"
      return str(value)

    for mapping in definition.parameters:
      group = inputs.get(mapping.location, {})
      if mapping.input_name not in group:
        continue
      value = group[mapping.input_name]
      if value is None:
        return failure(
          "input_validation",
          "Path/query/header parameters cannot be null",
          details={"path": [mapping.location, mapping.input_name]},
        )
      if mapping.location == "path":
        # RFC unreserved dots need explicit escaping here: HTTPX normalizes
        # literal dot segments before sending and would change the target path.
        encoded = quote(scalar(value), safe="").replace(".", "%2E")
        url = url.replace("{" + mapping.name + "}", encoded)
      elif mapping.location == "headers":
        try:
          check_header(mapping.name, scalar(value))
        except ValueError as error:
          return failure(
            "input_validation",
            str(error),
            details={"path": [mapping.location, mapping.input_name]},
          )
        headers[mapping.name] = scalar(value)
      elif isinstance(value, list):
        if mapping.explode is not False:
          query.extend((mapping.name, scalar(item)) for item in value)
        else:
          query.append((mapping.name, ",".join(scalar(item) for item in value)))
      else:
        query.append((mapping.name, scalar(value)))
    request_url = httpx.URL(url)
    if query:
      encoded = str(httpx.QueryParams(tuple(query))).encode("ascii")
      request_url = request_url.copy_with(
        query=request_url.query + (b"&" if request_url.query else b"") + encoded
      )
    content = None
    if "body" in inputs:
      content = json.dumps(inputs["body"], ensure_ascii=False, allow_nan=False).encode(
        "utf-8"
      )
      headers["Content-Type"] = "application/json"
    async with httpx.AsyncClient(follow_redirects=False, timeout=None) as client:
      async with client.stream(
        definition.method, request_url, headers=headers, content=content
      ) as response:
        mime = response.headers.get("content-type", "").split(";")[0].strip().lower()
        details: dict[str, JsonValue] = {
          "status_code": response.status_code,
          "content_type": mime,
          "headers": dict(response.headers),
        }
        chunks = bytearray()
        async for chunk in response.aiter_bytes():
          if len(chunks) + len(chunk) > OUTPUT_LIMIT:
            return failure(
              "output_limit", "HTTP response exceeds 1 MiB", details=details
            )
          chunks.extend(chunk)
        if (
          chunks
          and mime
          and not (
            mime.startswith("text/")
            or mime.endswith("+json")
            or mime.endswith("+xml")
            or mime
            in (
              "application/json",
              "application/xml",
              "application/javascript",
              "application/x-www-form-urlencoded",
            )
          )
        ):
          return failure(
            "unsupported_response",
            "Binary responses are not supported",
            details=details,
          )
        try:
          text = chunks.decode(response.encoding or "utf-8", errors="strict")
          if "\x00" in text:
            raise UnicodeError("Binary content")
        except (UnicodeError, LookupError):
          return failure(
            "unsupported_response",
            "Binary responses are not supported",
            details=details,
          )
        try:
          data = json.loads(text, parse_constant=reject_nonfinite)
          json.dumps(data, allow_nan=False)
        except json.JSONDecodeError:
          data = text
        except ValueError:
          return failure(
            "invalid_response",
            "Response contains a non-finite JSON value",
            details=details,
          )
        if 200 <= response.status_code < 300:
          return ToolResult(status="success", data=data, details=details)
        return failure(
          "http_status", f"HTTP {response.status_code}", data=data, details=details
        )


class ToolExecutor:
  def __init__(self):
    self.adapters = {"http": HttpAdapter()}

  async def execute(
    self,
    load: Callable[[], Awaitable[ToolDefinition]],
    inputs: dict,
    *,
    manual_test: bool = False,
  ) -> ToolResult:
    started = time.monotonic()
    try:
      definition = await load()
      async with asyncio.timeout(definition.timeout_seconds):
        result = await self._dispatch(definition, inputs, manual_test)
    except TimeoutError:
      result = ToolResult(
        status="timeout",
        error={"code": "timeout", "message": "Execution budget exceeded"},
      )
    except asyncio.CancelledError:
      result = ToolResult(
        status="cancelled",
        error={"code": "cancelled", "message": "Tool test cancelled"},
      )
    except httpx.HTTPError:
      result = failure("transport", "HTTP request or response reading failed")
    except Exception as error:
      result = failure(
        getattr(error, "code", "execution"),
        str(error) if hasattr(error, "code") else "Tool execution failed",
      )
    result.duration_ms = (time.monotonic() - started) * 1000
    return result

  async def _dispatch(
    self, definition: ToolDefinition, inputs: dict, manual_test: bool
  ) -> ToolResult:
    if not manual_test and not definition.enabled:
      return failure("disabled", "Tool is disabled")
    json.dumps(inputs, allow_nan=False)
    validator_class = get_schema_validator_class(definition.input_schema)
    validator = validator_class(definition.input_schema)
    error = next(validator.iter_errors(inputs), None)
    if error is not None:
      return failure(
        "input_validation", error.message, details={"path": list(error.absolute_path)}
      )
    adapter = self.adapters.get(definition.kind)
    if adapter is None:
      return failure("unsupported_kind", "Tool adapter is not registered")
    return await adapter.execute(definition, inputs)
