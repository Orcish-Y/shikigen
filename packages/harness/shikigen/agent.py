import logging
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain.chat_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph

from shikigen.app_config import AppConfig, load_app_config
from shikigen.middleware.goal_middleware import GoalEvaluator, GoalMiddleware
from shikigen.middleware.logging_middleware import LoggingMiddleware
from shikigen.middleware.tool_error_handling_middleware import (
  ToolErrorHandlingMiddleware,
)
from shikigen.model import create_chat_model
from shikigen.runtime_context import AgentRunContext
from shikigen.tools import ToolRegistry, build_task_tool, create_builtin_registry
from shikigen.tools.mcp_loader import load_mcp_tools

logger = logging.getLogger(__name__)


async def create_lead_agent(
  model: str | BaseChatModel | None = None,  # 显式模型覆盖创建配置
  tool_registry: ToolRegistry | None = None,  # 可选：工具注册表
  # 可选：额外 middleware
  middlewares: list[AgentMiddleware[Any, AgentRunContext]] | None = None,
  system_prompt: str | None = None,  # 可选：系统提示词
  checkpointer: BaseCheckpointSaver | None = None,
  *,
  task_tool_registry: ToolRegistry | None = None,
  config: AppConfig | None = None,
) -> CompiledStateGraph[Any, AgentRunContext, Any, Any]:
  """从配置创建模型和工具并组装 Agent。

  config 未传时读取默认配置文件；显式传入时不读取文件。
  每次构建只解析一次配置，读取或校验失败直接向调用者报告。
  显式 model / tool_registry 覆盖对应创建配置；空 registry 不补充工具。
  task_tool_registry 为 None 时沿用主工具集合；显式空集合禁用子 Agent 工具。
  checkpoint 由调用者管理，None 表示不启用。
  """

  resolved_config = config if config is not None else load_app_config()
  if model is None:
    model = create_chat_model(resolved_config.model)
  if tool_registry is None:
    _tool_registry = create_builtin_registry()
    _tool_registry.register_many(await load_mcp_tools(resolved_config.mcp))
  else:
    _tool_registry = tool_registry
  _task_tool_registry = (
    _tool_registry if task_tool_registry is None else task_tool_registry
  )

  tools = _tool_registry.list()
  task_tool = build_task_tool(
    model, _task_tool_registry, subagents=resolved_config.subagents
  )
  tools.append(task_tool)  # 将 task 工具添加到工具列表中

  agent_middlewares: list[AgentMiddleware[Any, AgentRunContext]] = [
    GoalMiddleware(evaluator=GoalEvaluator(model)),
    *(middlewares or []),
    ToolErrorHandlingMiddleware(),
    LoggingMiddleware(),
  ]
  agent = create_agent(
    model=model,
    tools=tools,
    middleware=agent_middlewares,
    context_schema=AgentRunContext,
    checkpointer=checkpointer,
    system_prompt=system_prompt or "You are a helpful assistant.",
  )

  logger.info(
    "Agent created with model: %s, tools: %s", model, [tool.name for tool in tools]
  )

  return agent
