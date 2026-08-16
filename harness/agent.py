import logging

from langchain.agents import create_agent
from langchain.chat_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph

from harness.checkpoint.json_checkpointer import JsonCheckpointer
from harness.runtime_context import AgentRunContext
from middleware.goal_middleware import GoalEvaluator, GoalMiddleware
from middleware.logging_middleware import LoggingMiddleware
from middleware.tool_error_handling_middleware import ToolErrorHandlingMiddleware
from tools import ToolRegistry, build_task_tool, create_builtin_registry

logger = logging.getLogger(__name__)


def create_lead_agent(
  model: str | BaseChatModel,  # 模型实例
  tool_registry: ToolRegistry | None = None,  # 可选：工具注册表
  middlewares: list | None = None,  # 可选：额外 middleware
  system_prompt: str | None = None,  # 可选：系统提示词
  checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:

  _tool_registry = tool_registry or create_builtin_registry()

  tools = _tool_registry.list()
  task_tool = build_task_tool(model, _tool_registry)
  tools.append(task_tool)  # 将 task 工具添加到工具列表中

  agent = create_agent(
    model=model,
    tools=tools,
    middleware=[
      GoalMiddleware(evaluator=GoalEvaluator(model)),
      *(middlewares or []),
      ToolErrorHandlingMiddleware(),
      LoggingMiddleware(),
    ],
    context_schema=AgentRunContext,
    checkpointer=checkpointer or JsonCheckpointer(),
    system_prompt=system_prompt or "You are a helpful assistant.",
  )

  logger.info(
    "Agent created with model: %s, tools: %s", model, [tool.name for tool in tools]
  )

  return agent
