"""Tool registry — manages registered tools."""

from typing import Callable

from langchain_core.tools import BaseTool

class ToolRegistry:
    """Registry for agent tools."""

    def __init__(self) -> None:
        self._tools: list[dict[str, BaseTool | Callable]] = []

    def register(self, t: BaseTool | Callable) -> None:
        """Register a tool."""
        name = t.name if isinstance(t, BaseTool) else getattr(t, "__name__", str(t))
        self._tools[name] = t

    def get_tools(self) -> list[BaseTool | Callable]:
        """Return all registered tools."""
        return list(self._tools.values())

    def remove(self, name: str) -> None:
        """Remove a tool by name."""
        self._tools.pop(name, None)
