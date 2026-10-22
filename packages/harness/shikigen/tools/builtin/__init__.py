"""供 Agent 使用的内置工具；注册和 Agent 组装位于 core。"""

from shikigen.tools.builtin.add import add
from shikigen.tools.builtin.filesystem import create_filesystem_tools
from shikigen.tools.builtin.get_current_time import get_current_time
from shikigen.tools.builtin.web_fetch import web_fetch_tool
from shikigen.tools.builtin.web_search_client import web_search_tool

__all__ = [
  "get_current_time",
  "add",
  "create_filesystem_tools",
  "web_fetch_tool",
  "web_search_tool",
]
