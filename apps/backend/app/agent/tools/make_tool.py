"""Tool decorator — creates LangChain tools from functions."""

import functools
from typing import Any, Callable

from langchain_core.tools import BaseTool, tool


def make_tool(
    name: str | None = None,
    description: str | None = None,
) -> Callable:
    """Decorator to create a LangChain tool from a function.

    Usage:
        @make_tool("search", "Search the web")
        def web_search(query: str) -> str:
            ...
    """
    def decorator(fn: Callable) -> BaseTool:
        @functools.wraps(fn)
        @tool(name or fn.__name__, description or fn.__doc__ or "")
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return fn(*args, **kwargs)

        return wrapper

    return decorator
