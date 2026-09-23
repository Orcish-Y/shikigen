import unittest
from unittest.mock import AsyncMock, patch

from langchain.messages import AIMessage
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from shikigen.app_config import (
  AppConfig,
  AppConfigError,
  McpConfig,
  ModelConfig,
  SubagentConfig,
  SubagentsConfig,
)
from shikigen.core.agent import create_lead_agent
from shikigen.tools import ToolRegistry, build_task_tool, create_builtin_registry


class AgentFactoryTests(unittest.IsolatedAsyncioTestCase):
  async def test_config_errors_propagate_before_loading_dependencies(self):
    for message in ("Config file not found", "Invalid config file"):
      with (
        self.subTest(message=message),
        patch(
          "shikigen.core.agent.load_app_config", side_effect=AppConfigError(message)
        ),
        patch("shikigen.core.agent.create_chat_model") as make_model,
        patch("shikigen.core.agent.load_mcp_tools", new=AsyncMock()) as load_tools,
      ):
        with self.assertRaisesRegex(AppConfigError, message):
          await create_lead_agent()
        make_model.assert_not_called()
        load_tools.assert_not_awaited()

  async def test_loads_dependencies_and_shares_model(self):
    model = FakeMessagesListChatModel(responses=[AIMessage(content="done")])
    builtin = create_builtin_registry()
    mcp_tool = builtin.tools["add"]
    registry = ToolRegistry().register(builtin.tools["read_file"])
    model_config = ModelConfig()
    mcp = McpConfig()
    subagents = SubagentsConfig()
    config = AppConfig(model=model_config, mcp=mcp, subagents=subagents)
    with (
      patch("shikigen.core.agent.load_app_config", return_value=config) as load_config,
      patch("shikigen.core.agent.create_chat_model", return_value=model) as make_model,
      patch("shikigen.core.agent.create_builtin_registry", return_value=registry),
      patch(
        "shikigen.core.agent.load_mcp_tools", new=AsyncMock(return_value=[mcp_tool])
      ) as load_tools,
      patch("shikigen.core.agent.build_task_tool", wraps=build_task_tool) as make_task,
      patch("shikigen.core.agent.create_agent") as make_agent,
    ):
      result = await create_lead_agent()

    load_config.assert_called_once_with()

    make_model.assert_called_once_with(model_config)
    load_tools.assert_awaited_once_with(mcp)
    self.assertIs(result, make_agent.return_value)
    self.assertIs(make_agent.call_args.kwargs["model"], model)
    self.assertEqual(
      [t.name for t in make_agent.call_args.kwargs["tools"]],
      ["read_file", "add", "task"],
    )
    make_task.assert_called_once_with(model, registry, subagents=subagents)

  async def test_injected_empty_registry_and_model_skip_loading(self):
    model = FakeMessagesListChatModel(responses=[AIMessage(content="done")])
    registry = ToolRegistry()
    with (
      patch(
        "shikigen.core.agent.load_app_config",
        side_effect=AssertionError("Unexpected file read"),
      ) as load_config,
      patch("shikigen.core.agent.create_chat_model") as make_model,
      patch("shikigen.core.agent.create_builtin_registry") as make_builtin,
      patch("shikigen.core.agent.load_mcp_tools", new=AsyncMock()) as load_tools,
      patch("shikigen.core.agent.create_agent") as make_agent,
    ):
      await create_lead_agent(
        model,
        tool_registry=registry,
        config=AppConfig(model=ModelConfig(), mcp=McpConfig()),
      )
    load_config.assert_not_called()
    make_model.assert_not_called()
    make_builtin.assert_not_called()
    load_tools.assert_not_awaited()
    self.assertEqual(registry.names, [])
    self.assertEqual([t.name for t in make_agent.call_args.kwargs["tools"]], ["task"])

  async def test_per_type_policy_empty_deny_and_framework_restriction(self):
    registry = create_builtin_registry()
    model = FakeMessagesListChatModel(responses=[AIMessage(content="done")])
    registry.register(build_task_tool(model, ToolRegistry()))
    original = registry.names
    policy = SubagentsConfig(
      general=SubagentConfig(tools=[]),
      bash=SubagentConfig(
        tools=["bash", "write_file", "web_search", "task"],
        disallowed_tools=["write_file"],
      ),
    )
    task = build_task_tool(model, registry, subagents=policy)
    for agent_type, expected in (("general", set()), ("bash", {"bash", "web_search"})):
      with self.subTest(agent_type=agent_type):
        child = AsyncMock()
        child.ainvoke.return_value = {"messages": [AIMessage(content="done")]}
        with patch("shikigen.tools.task_tool.create_agent", return_value=child) as make:
          await task.ainvoke({"description": "inspect", "agent_type": agent_type})
        self.assertEqual({t.name for t in make.call_args.kwargs["tools"]}, expected)
    self.assertEqual(registry.names, original)

  async def test_unavailable_allowlist_does_not_fall_back_to_all_tools(self):
    registry = create_builtin_registry()
    model = FakeMessagesListChatModel(responses=[AIMessage(content="done")])
    with self.assertLogs("shikigen.tools.task_tool", level="WARNING") as logs:
      task = build_task_tool(
        model,
        registry,
        subagents=SubagentsConfig(general=SubagentConfig(tools=["missing_mcp_tool"])),
      )
    self.assertIn("missing_mcp_tool", " ".join(logs.output))
    child = AsyncMock()
    child.ainvoke.return_value = {"messages": [AIMessage(content="done")]}
    with patch("shikigen.tools.task_tool.create_agent", return_value=child) as make:
      await task.ainvoke({"description": "inspect"})
    self.assertEqual(make.call_args.kwargs["tools"], [])


if __name__ == "__main__":
  unittest.main()
