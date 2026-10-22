"""执行观察中的已知认证值遮盖；不改变保存配置或实际传输。"""

import json
import re
from urllib.parse import parse_qsl, quote, quote_plus, urlsplit

from shikigen.contracts.tool_definitions import HttpToolDefinition
from shikigen.contracts.tool_execution import McpToolExecution, ToolExecution


def execution_secrets(execution: ToolExecution) -> tuple[str, ...]:
  values: list[str] = []

  def sensitive_fields(items):
    values.extend(
      value
      for name, value in items
      if re.search(r"authorization|cookie|token|secret|password|key", name, re.I)
    )

  definition = execution.definition
  url = ""
  if isinstance(definition, HttpToolDefinition):
    values.extend(binding.value for binding in definition.auth)
    sensitive_fields(definition.headers.items())
    url = definition.url
  elif isinstance(execution, McpToolExecution):
    connection = execution.connection
    if connection.transport == "streamable_http":
      sensitive_fields(connection.headers.items())
      url = connection.url
    else:
      sensitive_fields(connection.env.items())
  if url:
    parsed = urlsplit(url)
    values.append(parsed.password or "")
    sensitive_fields(parse_qsl(parsed.query))
  # Bearer 前缀由用户填写或适配器添加，两种回显都必须遮盖。
  values.extend(
    value[7:] for value in tuple(values) if value.lower().startswith("bearer ")
  )
  return tuple({value for value in values if value})


def redact_tool_value(value, secrets: tuple[str, ...]):
  variants = {
    variant
    for secret in secrets
    for variant in (
      secret,
      quote(secret, safe=""),
      quote_plus(secret),
      json.dumps(secret, ensure_ascii=True)[1:-1],
      json.dumps(secret, ensure_ascii=False)[1:-1],
    )
    if variant
  }
  if not variants:
    return value
  pattern = re.compile(
    "|".join(re.escape(item) for item in sorted(variants, key=len, reverse=True))
  )

  def redact(item):
    if isinstance(item, str):
      return pattern.sub("[REDACTED]", item)
    if isinstance(item, list):
      return [redact(child) for child in item]
    if isinstance(item, dict):
      return {redact(key): redact(child) for key, child in item.items()}
    return item

  return redact(value)
