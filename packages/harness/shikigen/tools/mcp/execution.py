"""MCP 原始协议结果适配；不经 LangChain 内容转换丢弃附加字段。"""

import json

from jsonschema import validate
from jsonschema.exceptions import SchemaError, ValidationError
from mcp import types
from referencing import Registry
from referencing.exceptions import Unresolvable

from shikigen.contracts.tool_execution import (
  McpToolExecution,
  ToolExecution,
  ToolExecutionContext,
)
from shikigen.contracts.tool_results import ToolResult, failure
from shikigen.tools.mcp.sessions import (
  MCP_RESULT_LIMIT,
  McpSessionProvider,
  list_mcp_session_tools,
  mcp_exception_code,
  mcp_exception_message,
)


class McpAdapter:
  def __init__(self, mcp_session_provider: McpSessionProvider):
    self.mcp_session_provider = mcp_session_provider

  async def execute(
    self, execution: ToolExecution, inputs: dict, *, context: ToolExecutionContext
  ) -> ToolResult:
    if not isinstance(execution, McpToolExecution):
      return failure("configuration", "Expected a prepared MCP tool execution")
    definition = execution.definition
    details = context.details
    details.update(
      connection_id=definition.connection_id,
      remote_name=definition.remote_name,
      transport=execution.connection.transport,
    )
    try:
      async with self.mcp_session_provider.open_mcp_session(
        execution.connection
      ) as mcp_session:
        await mcp_session.initialize()
        sources = await list_mcp_session_tools(mcp_session)
        source = next(
          (tool for tool in sources if tool["name"] == definition.remote_name), None
        )
        if source is None:
          return failure(
            "mcp_tool_missing", "Remote tool is not available", details=details
          )
        details["source_tool"] = source
        # 使用公开低层请求保留原结果，再执行 SDK 同等的来源输出校验。
        # mcp_session.call_tool 在输出校验抛错时不提供原始返回值。
        result = await mcp_session.send_request(
          types.ClientRequest(
            types.CallToolRequest(
              params=types.CallToolRequestParams(
                name=definition.remote_name,
                arguments=inputs,
              )
            )
          ),
          types.CallToolResult,
        )
        raw = result.model_dump(mode="json", by_alias=True, exclude_unset=True)
        size = len(json.dumps(raw, ensure_ascii=False, allow_nan=False).encode("utf-8"))
        if size > MCP_RESULT_LIMIT:
          details.update(received_bytes=size, limit_bytes=MCP_RESULT_LIMIT)
          return failure(
            "output_limit",
            "MCP result exceeds 1 MiB; full result omitted",
            details=details,
          )
        details["raw_result"] = raw
        data = (
          raw["structuredContent"]
          if result.structuredContent is not None
          else raw.get("content", [])
        )
        if result.isError:
          return failure(
            "mcp_tool_error", "MCP tool reported isError", data=data, details=details
          )
        output_schema = source.get("outputSchema")
        if output_schema is not None:
          try:
            if result.structuredContent is None:
              raise ValueError(
                "Tool declared outputSchema but omitted structuredContent"
              )
            validate(result.structuredContent, output_schema, registry=Registry())
          except (ValidationError, SchemaError, ValueError, Unresolvable) as error:
            return failure(
              "mcp_output_validation", str(error), data=data, details=details
            )
        return ToolResult(status="success", data=data, details=details)
    except Exception as error:
      return failure(
        mcp_exception_code(error), mcp_exception_message(error), details=details
      )
