from collections.abc import Callable
from typing import override

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain.messages import ToolMessage
from langgraph.errors import GraphBubbleUp


class ToolErrorHandlingMiddleware(AgentMiddleware):
  """Return a structured tool error so the agent can respond to a failed tool."""

  def __init__(self):
    pass

  @override
  def wrap_tool_call(
    self,
    request: ModelRequest,
    handler: Callable[[ModelRequest], ModelResponse],
  ) -> ModelResponse:
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
    request: ModelRequest,
    handler: Callable[[ModelRequest], ModelResponse],
  ) -> ModelResponse:
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
