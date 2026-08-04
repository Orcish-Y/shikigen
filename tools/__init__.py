from __future__ import annotations

import logging

from langchain_core.tools import BaseTool

from tools.add import add
from tools.filesystem import read_file, write_file
from tools.get_current_time import get_current_time
from tools.web_fetch import web_fetch_tool
from tools.web_search_client import web_search_tool

logger = logging.getLogger(__name__)


class ToolRegistry:
  def __init__(self) -> None:
    self.tools: dict[str, BaseTool] = {}

  def register(self, tool: BaseTool) -> ToolRegistry:
    """注册一个工具。同名工具后来的被忽略（先注册的优先）。返回 self 支持链式调用。"""
    if tool.name in self.tools:
      logger.warning("Tool %r is already registered; skipping duplicate.", tool.name)
      return self
    self.tools[tool.name] = tool
    return self

  def register_many(self, tools: list[BaseTool]) -> ToolRegistry:
    """批量注册。"""
    for tool in tools:
      self.register(tool)
    return self

  def list(self) -> list[BaseTool]:
    """返回所有已注册工具的列表。"""
    return list(self.tools.values())

  @property
  def names(self) -> list[str]:
    """返回已注册工具名的排序列表。"""
    return sorted(self.tools.keys())


def create_default_registry() -> ToolRegistry:
  """创建并返回一个预填了所有本地工具的注册表。"""
  registry = ToolRegistry()
  registry.register_many(
    [get_current_time, add, read_file, write_file, web_fetch_tool, web_search_tool]
  )
  return registry
