import datetime
import logging
from collections.abc import Awaitable, Callable
from typing import Any, override

from langchain.agents.middleware import (
  AgentMiddleware,
  AgentState,
  ToolCallRequest,
)
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.runtime import Runtime
from langgraph.types import Command

logger = logging.getLogger(__name__)


class LoggingMiddleware(AgentMiddleware[AgentState, Any]):
  @override
  async def abefore_model(self, state: AgentState, runtime: Runtime):
    # 记录消息数量
    logger.info("Messages count: %d", len(state["messages"]))

  @override
  async def aafter_model(self, state: AgentState, runtime: Runtime):
    # 记录 LLM 决定调用的工具名
    message = state["messages"][-1]

    if isinstance(message, AIMessage) and message.tool_calls:
      tool_info = [
        (tool.get("name"), tool.get("args", {})) for tool in message.tool_calls
      ]
      logger.info("Tool call: %s", tool_info)

  @override
  async def awrap_tool_call(
    self,
    request: ToolCallRequest,
    handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
  ) -> ToolMessage | Command[Any]:

    began = datetime.datetime.now()
    response = await handler(request)
    finished = datetime.datetime.now()
    duration = (finished - began).total_seconds()
    logger.info("Tool call took %.2f seconds", duration)
    return response
