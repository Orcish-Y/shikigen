from collections.abc import Awaitable, Callable
from typing import Any, override

from langchain.agents.middleware import AgentMiddleware, AgentState, ToolCallRequest
from langchain.messages import ToolMessage
from langgraph.errors import GraphBubbleUp
from langgraph.types import Command


class ToolErrorHandlingMiddleware(AgentMiddleware[AgentState, Any]):
  """Return a structured tool error so the agent can respond to a failed tool."""

  def __init__(self):
    pass

  @override
  def wrap_tool_call(
    self,
    request: ToolCallRequest,
    handler: Callable[[ToolCallRequest], ToolMessage | Command[Any]],
  ) -> ToolMessage | Command[Any]:
    try:
      response = handler(request)
      return response
    except GraphBubbleUp:
      raise
    except Exception as exc:
      return ToolMessage(
        content=f"Tool execution failed: {exc}",
        name=request.tool_call["name"],
        tool_call_id=request.tool_call["id"],
        status="error",
      )

  @override
  async def awrap_tool_call(
    self,
    request: ToolCallRequest,
    handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
  ) -> ToolMessage | Command[Any]:
    try:
      response = await handler(request)
      return response
    except GraphBubbleUp:
      raise
    except Exception as exc:
      return ToolMessage(
        content=f"Tool execution failed: {exc}",
        name=request.tool_call["name"],
        tool_call_id=request.tool_call["id"],
        status="error",
      )
