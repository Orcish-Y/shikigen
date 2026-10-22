"""HTTP 工具适配器：请求构建、传输和响应处理。"""

import json
from urllib.parse import quote

import httpx

from shikigen.contracts.http_requests import check_header
from shikigen.contracts.tool_definitions import HttpToolDefinition, ToolDefinition
from shikigen.contracts.tool_execution import ToolExecution, ToolExecutionContext
from shikigen.contracts.tool_results import ToolResult, failure

OUTPUT_LIMIT = 1024 * 1024


def reject_nonfinite(value: str):
  raise ValueError(f"Non-finite JSON value: {value}")


class HttpAdapter:
  async def execute(
    self,
    execution: ToolExecution,
    inputs: dict,
    *,
    context: ToolExecutionContext,
  ) -> ToolResult:
    try:
      return await self._execute_request(execution.definition, inputs, context)
    except httpx.HTTPError:
      return failure(
        "transport", "HTTP request or response reading failed", details=context.details
      )

  async def _execute_request(
    self, definition: ToolDefinition, inputs: dict, context: ToolExecutionContext
  ) -> ToolResult:
    if not isinstance(definition, HttpToolDefinition):
      return failure("configuration", "Expected an HTTP tool definition")
    url = definition.url
    headers = dict(definition.headers)
    query: list[tuple[str, str]] = []
    for binding in definition.auth:
      secret = binding.value
      if not secret:
        return failure("authentication_missing", "Authentication credential is not set")
      value = secret
      if binding.kind == "bearer" and not secret.lower().startswith("bearer "):
        value = "Bearer " + secret
      if binding.location == "headers":
        headers[binding.name] = value
      else:
        query.append((binding.name, value))
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
        details = context.details
        details.update(
          status_code=response.status_code,
          content_type=mime,
          headers=dict(response.headers),
        )
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
