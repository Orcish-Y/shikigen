import unittest
from unittest.mock import AsyncMock, Mock, patch

from harness.app_config import McpConfig
from tools.mcp_loader import load_mcp_tools


class McpLoaderTests(unittest.IsolatedAsyncioTestCase):
  async def test_empty_config_returns_no_tools_without_creating_client(self) -> None:
    with patch("tools.mcp_loader.MultiServerMCPClient") as client_class:
      tools = await load_mcp_tools(McpConfig())

    self.assertEqual(tools, [])
    client_class.assert_not_called()

  async def test_loads_and_combines_tools_from_each_server(self) -> None:
    first_tool = Mock(name="first_tool")
    second_tool = Mock(name="second_tool")
    client = Mock()

    async def get_tools(*, server_name: str):
      return {
        "first": [first_tool],
        "second": [second_tool],
      }[server_name]

    client.get_tools = AsyncMock(side_effect=get_tools)
    config = McpConfig.model_validate(
      {
        "servers": {
          "first": {"transport": "http", "url": "https://first.example/mcp"},
          "second": {"transport": "http", "url": "https://second.example/mcp"},
        }
      }
    )
    connections = {
      name: server.model_dump(exclude_none=True)
      for name, server in config.servers.items()
    }

    with patch(
      "tools.mcp_loader.MultiServerMCPClient",
      return_value=client,
    ) as client_class:
      tools = await load_mcp_tools(config)

    self.assertEqual(tools, [first_tool, second_tool])
    client_class.assert_called_once_with(connections, tool_name_prefix=True)
    self.assertEqual(client.get_tools.await_count, 2)
    client.get_tools.assert_any_await(server_name="first")
    client.get_tools.assert_any_await(server_name="second")

  async def test_skips_failed_server_and_keeps_healthy_tools(self) -> None:
    healthy_tool = Mock(name="healthy_tool")
    client = Mock()

    async def get_tools(*, server_name: str):
      if server_name == "broken":
        raise ConnectionError("server unavailable")
      return [healthy_tool]

    client.get_tools = AsyncMock(side_effect=get_tools)
    config = McpConfig.model_validate(
      {
        "servers": {
          "broken": {
            "transport": "http",
            "url": "https://broken.example/mcp",
          },
          "healthy": {
            "transport": "http",
            "url": "https://healthy.example/mcp",
          },
        }
      }
    )

    with (
      patch("tools.mcp_loader.MultiServerMCPClient", return_value=client),
      self.assertLogs("tools.mcp_loader", level="WARNING") as logs,
    ):
      tools = await load_mcp_tools(config)

    self.assertEqual(tools, [healthy_tool])
    self.assertEqual(client.get_tools.await_count, 4)
    self.assertEqual(
      sum(
        call.kwargs["server_name"] == "broken"
        for call in client.get_tools.await_args_list
      ),
      3,
    )
    self.assertIn("broken", logs.output[-1])
    self.assertIn("after 3 attempts", logs.output[-1])

  async def test_stops_retrying_after_a_server_connects(self) -> None:
    recovered_tool = Mock(name="recovered_tool")
    client = Mock()
    client.get_tools = AsyncMock(
      side_effect=[
        ConnectionError("first failure"),
        ConnectionError("second failure"),
        [recovered_tool],
      ]
    )
    config = McpConfig.model_validate(
      {
        "servers": {
          "recovering": {
            "transport": "http",
            "url": "https://recovering.example/mcp",
          }
        }
      }
    )

    with (
      patch("tools.mcp_loader.MultiServerMCPClient", return_value=client),
      self.assertLogs("tools.mcp_loader", level="WARNING"),
    ):
      tools = await load_mcp_tools(config)

    self.assertEqual(tools, [recovered_tool])
    self.assertEqual(client.get_tools.await_count, 3)

  async def test_uses_configured_initial_max_attempts(self) -> None:
    client = Mock()
    client.get_tools = AsyncMock(side_effect=ConnectionError("unavailable"))
    config = McpConfig.model_validate(
      {
        "initial_max_attempts": 2,
        "servers": {
          "broken": {
            "transport": "http",
            "url": "https://broken.example/mcp",
          }
        },
      }
    )

    with (
      patch("tools.mcp_loader.MultiServerMCPClient", return_value=client),
      self.assertLogs("tools.mcp_loader", level="WARNING") as logs,
    ):
      tools = await load_mcp_tools(config)

    self.assertEqual(tools, [])
    self.assertEqual(client.get_tools.await_count, 2)
    self.assertIn("after 2 attempts", logs.output[-1])


if __name__ == "__main__":
  unittest.main()
