"""Utilities for invoking async tools from synchronous agent paths."""

import asyncio
import atexit
import concurrent.futures
import contextvars
import functools
import logging
from collections.abc import Callable
from typing import Any

from langchain_core.runnables import RunnableConfig

logger = logging.getLogger(__name__)

_TOOL_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=10, thread_name_prefix="tool-sync"
)

atexit.register(lambda: _TOOL_EXECUTOR.shutdown(wait=False))


def make_sync_tool_wrapper(coro: Callable[..., Any], tool_name: str) -> Callable[..., Any]:
    """Build a synchronous wrapper for an asynchronous tool coroutine.

    If already inside a running event loop, offloads to a thread pool;
    otherwise uses asyncio.run() directly.
    """

    def run_coroutine(*args: Any, **kwargs: Any) -> Any:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        try:
            if loop is not None and loop.is_running():
                context = contextvars.copy_context()
                future = _TOOL_EXECUTOR.submit(
                    context.run, lambda: asyncio.run(coro(*args, **kwargs))
                )
                return future.result()
            return asyncio.run(coro(*args, **kwargs))
        except Exception as e:
            logger.error(
                "Error invoking tool %r via sync wrapper: %s", tool_name, e, exc_info=True
            )
            raise

    def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
        return run_coroutine(*args, **kwargs)

    return sync_wrapper


def ensure_sync_invocable(tool: Any) -> Any:
    """Attach a sync wrapper to async-only tools.

    Safe to call repeatedly — does nothing if tool already has a sync func.
    """
    if hasattr(tool, "func") and hasattr(tool, "coroutine"):
        if tool.func is None and tool.coroutine is not None:
            tool.func = make_sync_tool_wrapper(tool.coroutine, tool.name)
    return tool
