"""组装 Agent 使用的内置工具与启动配置中的 MCP 工具。"""

from pathlib import Path

from shikigen.app_config import AppConfig
from shikigen.core.mcp_loader import load_mcp_tools
from shikigen.core.tool_registry import ToolRegistry
from shikigen.tools import (
  add,
  create_filesystem_tools,
  get_current_time,
  web_fetch_tool,
  web_search_tool,
)


def create_builtin_registry(workspace_root: str | Path = ".") -> ToolRegistry:
  """创建内置工具集合；文件工具绑定创建时解析的工作区根目录。"""
  return ToolRegistry().register_many(
    [
      get_current_time,
      add,
      *create_filesystem_tools(workspace_root),
      web_fetch_tool,
      web_search_tool,
    ]
  )


async def create_agent_tool_registry(config: AppConfig) -> ToolRegistry:
  """按配置绑定工作区并合并 MCP 工具，同名时优先使用内置工具。"""
  registry = create_builtin_registry(config.workspace_root)
  registry.register_many(await load_mcp_tools(config.mcp))
  return registry
