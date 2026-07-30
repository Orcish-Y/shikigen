import logging

from langchain.agents import create_agent
from langchain.chat_models import BaseChatModel
from langgraph.graph.state import CompiledStateGraph

from middleware.logging_middleware import LoggingMiddleware
from middleware.tool_error_handling_middleware import ToolErrorHandlingMiddleware
from tools import ToolRegistry, create_default_registry

logger = logging.getLogger(__name__)


def create_lead_agent(
  model: str | BaseChatModel,  # 模型实例
  tool_registry: ToolRegistry | None = None,  # 可选：工具注册表
  middlewares: list | None = None,  # 可选：额外 middleware
  system_prompt: str | None = None,  # 可选：系统提示词
) -> CompiledStateGraph:

  tools = tool_registry.list() if tool_registry else create_default_registry().list()

  agent = create_agent(
    model=model,
    tools=tools,
    middleware=[
      ToolErrorHandlingMiddleware(),
      LoggingMiddleware(),
      *(middlewares or []),
    ],
    system_prompt=system_prompt or "You are a helpful assistant.",
  )

  logger.info(
    "Agent created with model: %s, tools: %s", model, [tool.name for tool in tools]
  )

  return agent
