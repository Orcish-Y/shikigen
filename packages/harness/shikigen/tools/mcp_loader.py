from __future__ import annotations

import asyncio
import logging
from typing import cast

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.sessions import Connection

from shikigen.app_config import McpConfig

logger = logging.getLogger(__name__)


async def _load_server_tools(
  client: MultiServerMCPClient,
  server_name: str,
  max_attempts: int,
) -> list[BaseTool]:
  """Discover one server's tools, retrying startup failures in isolation."""
  for attempt in range(1, max_attempts + 1):
    try:
      tools = await client.get_tools(server_name=server_name)
      break
    except Exception:
      if attempt == max_attempts:
        logger.warning(
          "Failed to load tools from MCP server %r after %d attempts; skipping it.",
          server_name,
          attempt,
          exc_info=True,
        )
        return []

      logger.warning(
        "Failed to load tools from MCP server %r (attempt %d/%d); retrying.",
        server_name,
        attempt,
        max_attempts,
        exc_info=True,
      )

  logger.info("Loaded %d tool(s) from MCP server %r.", len(tools), server_name)
  return tools


async def load_mcp_tools(
  config: McpConfig,
) -> list[BaseTool]:
  """Load LangChain tools from all configured MCP servers.

  Each server is discovered independently so one unavailable server does not
  prevent healthy servers from contributing tools.
  """
  if not config.servers:
    return []

  connections = {
    name: cast(Connection, server.model_dump(exclude_none=True))
    for name, server in config.servers.items()
  }
  client = MultiServerMCPClient(
    connections,
    tool_name_prefix=True,
  )
  tools_by_server = await asyncio.gather(
    *(
      _load_server_tools(client, server_name, config.initial_max_attempts)
      for server_name in connections
    )
  )

  return [tool for server_tools in tools_by_server for tool in server_tools]
