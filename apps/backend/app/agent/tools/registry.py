"""Tool registry — manages registered tools."""

from app.community.baidu.tool import web_search_tool
from app.community.jina_ai.tool import web_fetch_tool
from langchain_core.tools import BaseTool


class ToolRegistry:
    """Registry for agent tools."""

    tools = [web_fetch_tool, web_search_tool]

    def register(self, t: BaseTool) -> None:
        """Register a tool."""
        name = t.name if isinstance(t, BaseTool) else getattr(t, "__name__", str(t))
        self.tools.append(t)

    def get_tools(self) -> list[BaseTool]:
        """Return all registered tools."""
        return list(self.tools)

    def remove(self, name: str) -> None:
        """Remove a tool by name."""
        self.tools = [t for t in self.tools if getattr(t, "name", str(t)) != name]
