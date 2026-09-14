from __future__ import annotations

import unittest
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import patch

from langchain.agents import create_agent
from langchain.messages import AIMessage, HumanMessage
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import Field
from shikigen import create_lead_agent
from shikigen.app_config import AppConfig, McpConfig, ModelConfig
from shikigen.checkpoint.json_checkpointer import JsonCheckpointer
from shikigen.tools import (
  ToolRegistry,
  build_task_tool,
  create_builtin_registry,
)


class ToolAwareFakeChatModel(FakeMessagesListChatModel):
  bound_tool_names: list[str] = Field(default_factory=list)

  def bind_tools(
    self,
    tools,
    *,
    tool_choice=None,
    **kwargs: Any,
  ) -> ToolAwareFakeChatModel:
    self.bound_tool_names = [tool.name for tool in tools]
    return self


class TaskToolTests(unittest.IsolatedAsyncioTestCase):
  def setUp(self):
    self.app_config = AppConfig(model=ModelConfig(), mcp=McpConfig())

  async def test_delegation_uses_configured_child_tools(self) -> None:
    for mode in ("omitted", "none", "filtered", "empty"):
      for agent_type in ("general", "bash"):
        with self.subTest(mode=mode, agent_type=agent_type):
          registry = create_builtin_registry()
          original_names = registry.names
          kwargs = {}
          expected = set(original_names)
          if mode == "none":
            kwargs["task_tool_registry"] = None
          elif mode == "filtered":
            child_registry = registry.excluding({"bash", "write_file"})
            kwargs["task_tool_registry"] = child_registry
            expected = set(child_registry.names)
          elif mode == "empty":
            kwargs["task_tool_registry"] = ToolRegistry()
            expected = set()
          if agent_type == "bash":
            expected &= {"bash", "read_file", "write_file", "list_dir", "grep"}
          model = ToolAwareFakeChatModel(
            responses=[
              AIMessage(
                content="",
                tool_calls=[
                  {
                    "name": "task",
                    "args": {"description": "inspect", "agent_type": agent_type},
                    "id": "delegation",
                  }
                ],
              ),
              AIMessage(content="child result"),
              AIMessage(content="done"),
            ]
          )
          agent = await create_lead_agent(
            model, config=self.app_config, tool_registry=registry, **kwargs
          )
          with patch(
            "shikigen.tools.task_tool.create_agent", wraps=create_agent
          ) as create_child:
            result = await agent.ainvoke(
              {"messages": [HumanMessage(content="delegate inspection")]}
            )

          create_child.assert_called_once()
          child_args = create_child.call_args.kwargs
          self.assertEqual({tool.name for tool in child_args["tools"]}, expected)
          available = ", ".join(tool.name for tool in child_args["tools"]) or "无"
          self.assertIn(f"本次实际可用工具：{available}。", child_args["system_prompt"])
          self.assertEqual(set(model.bound_tool_names), set(original_names) | {"task"})
          self.assertEqual(registry.names, original_names)
          self.assertEqual(result["messages"][-1].text, "done")

  async def test_lead_agent_runs_without_checkpoint_or_thread_id(self) -> None:
    for kwargs in ({}, {"checkpointer": None}):
      with self.subTest(kwargs=kwargs):
        model = ToolAwareFakeChatModel(responses=[AIMessage(content="done")])
        agent = await create_lead_agent(model, config=self.app_config, **kwargs)

        self.assertIsNone(agent.checkpointer)
        result = await agent.ainvoke(
          {"messages": [HumanMessage(content="hello")]},
        )

        self.assertEqual(result["messages"][-1].text, "done")

  async def test_explicit_json_checkpoint_restores_conversation(self) -> None:
    with TemporaryDirectory() as directory:
      saver = JsonCheckpointer(base_dir=directory)
      model = ToolAwareFakeChatModel(responses=[AIMessage(content="first reply")])
      agent = await create_lead_agent(model, config=self.app_config, checkpointer=saver)
      self.assertIs(agent.checkpointer, saver)
      config = {"configurable": {"thread_id": "explicit-json"}}
      await agent.ainvoke(
        {"messages": [HumanMessage(content="first question")]}, config=config
      )

      restored_agent = await create_lead_agent(
        ToolAwareFakeChatModel(responses=[AIMessage(content="second reply")]),
        config=self.app_config,
        checkpointer=JsonCheckpointer(base_dir=directory),
      )
      result = await restored_agent.ainvoke(
        {"messages": [HumanMessage(content="second question")]}, config=config
      )

      self.assertEqual(
        [message.text for message in result["messages"]],
        ["first question", "first reply", "second question", "second reply"],
      )

  async def test_rejects_an_unknown_agent_type(self) -> None:
    model = ToolAwareFakeChatModel(responses=[AIMessage(content="done")])
    task = build_task_tool(model, create_builtin_registry())

    with self.assertRaises(ValueError):
      await task.ainvoke({"description": "inspect the workspace", "agent_type": "typo"})

  async def test_returns_text_from_structured_model_content(self) -> None:
    model = ToolAwareFakeChatModel(
      responses=[AIMessage(content=[{"type": "text", "text": "done"}])]
    )
    task = build_task_tool(model, create_builtin_registry())

    result = await task.ainvoke({"description": "inspect the workspace"})

    self.assertEqual(result, "done")

  async def test_bash_agent_only_receives_workspace_tools(self) -> None:
    model = ToolAwareFakeChatModel(responses=[AIMessage(content="done")])
    task = build_task_tool(model, create_builtin_registry())

    await task.ainvoke({"description": "inspect the workspace", "agent_type": "bash"})

    self.assertEqual(
      set(model.bound_tool_names),
      {"bash", "read_file", "write_file", "list_dir", "grep"},
    )

  async def test_lead_agent_can_delegate_to_the_task_tool(self) -> None:
    model = ToolAwareFakeChatModel(
      responses=[
        AIMessage(
          content="",
          tool_calls=[
            {
              "name": "task",
              "args": {
                "description": "write and run hello.py",
                "agent_type": "bash",
              },
              "id": "task-call",
            }
          ],
        ),
        AIMessage(content="hello.py prints hello"),
        AIMessage(content="The delegated task completed."),
      ]
    )
    lead_agent = await create_lead_agent(
      model, config=self.app_config, checkpointer=InMemorySaver()
    )

    result = await lead_agent.ainvoke(
      {"messages": [HumanMessage(content="write and run hello.py")]},
      config={"configurable": {"thread_id": "task-tool-test"}},
    )

    self.assertEqual(result["messages"][-1].text, "The delegated task completed.")
