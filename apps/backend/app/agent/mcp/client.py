"""MCP client — connects to external MCP servers and exposes their tools."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from langchain_core.tools import BaseTool

logger = logging.getLogger(__name__)


@dataclass
class MCPServerConfig:
    """Configuration for an MCP server connection."""

    name: str
    transport: str = "stdio"  # "stdio" | "sse" | "streamable-http"
    command: str | None = None  # for stdio: e.g. "npx"
    args: list[str] = field(default_factory=list)  # e.g. ["-y", "@anthropic/mcp-server-filesystem"]
    env: dict[str, str] = field(default_factory=dict)
    url: str | None = None  # for sse/http transports
    headers: dict[str, str] = field(default_factory=dict)


class MCPClientManager:
    """Manages connections to multiple MCP servers.

    Each MCP server's tools are exposed to the agent.
    """

    def __init__(self, servers: list[MCPServerConfig] | None = None) -> None:
        self._servers: dict[str, MCPServerConfig] = {}
        self._sessions: dict[str, Any] = {}  # MCP ClientSession objects
        self._tools: list[BaseTool | Callable] = []

        for s in (servers or []):
            self.add_server(s)

    def add_server(self, config: MCPServerConfig) -> None:
        """Register an MCP server."""
        self._servers[config.name] = config

    def remove_server(self, name: str) -> None:
        """Remove a registered MCP server."""
        self._servers.pop(name, None)

    def list_servers(self) -> list[str]:
        """List registered server names."""
        return list(self._servers.keys())

    @staticmethod
    def _make_tool_from_mcp(name: str, description: str, schema: dict) -> Callable:
        """Create a callable wrapper for an MCP tool."""

        async def mcp_tool_wrapper(**kwargs: Any) -> str:
            # This will be replaced with actual MCP tool invocation
            return f"MCP tool '{name}' called with {kwargs}"

        mcp_tool_wrapper.__name__ = name
        mcp_tool_wrapper.__doc__ = description
        return mcp_tool_wrapper

    async def connect_all(self) -> None:
        """Connect to all registered MCP servers.

        Uses the official `mcp` Python package for client connections.
        """
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
            from mcp.client.sse import sse_client
        except ImportError:
            logger.warning(
                "`mcp` package not installed. Install with: uv add mcp"
            )
            return

        for name, config in self._servers.items():
            try:
                if config.transport == "stdio" and config.command:
                    params = StdioServerParameters(
                        command=config.command,
                        args=config.args,
                        env=config.env,
                    )
                    async with stdio_client(params) as (read, write):
                        async with ClientSession(read, write) as session:
                            await session.initialize()
                            tools_result = await session.list_tools()
                            for t in tools_result.tools:
                                wrapper = self._make_tool_from_mcp(
                                    t.name, t.description or "", t.inputSchema
                                )
                                self._tools.append(wrapper)
                            self._sessions[name] = session
                            logger.info(
                                "Connected to MCP server %r (%d tools)",
                                name,
                                len(tools_result.tools),
                            )

                elif config.transport in ("sse", "streamable-http") and config.url:
                    async with sse_client(config.url, headers=config.headers) as (
                        read,
                        write,
                    ):
                        async with ClientSession(read, write) as session:
                            await session.initialize()
                            tools_result = await session.list_tools()
                            for t in tools_result.tools:
                                wrapper = self._make_tool_from_mcp(
                                    t.name, t.description or "", t.inputSchema
                                )
                                self._tools.append(wrapper)
                            self._sessions[name] = session
                            logger.info(
                                "Connected to MCP server %r via %s (%d tools)",
                                name,
                                config.transport,
                                len(tools_result.tools),
                            )
            except Exception:
                logger.exception("Failed to connect to MCP server %r", name)

    async def disconnect_all(self) -> None:
        """Disconnect from all MCP servers."""
        self._sessions.clear()
        self._tools.clear()

    def get_tools(self) -> list[BaseTool | Callable]:
        """Return all tools from connected MCP servers."""
        return list(self._tools)
