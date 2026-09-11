from __future__ import annotations

import unittest
from typing import Any

from langchain.messages import AIMessage, HumanMessage
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import Field
from shikigen import create_lead_agent
from shikigen.tools import BASH_ONLY_TOOLS, build_task_tool, create_builtin_registry


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

    self.assertEqual(set(model.bound_tool_names), BASH_ONLY_TOOLS)

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
    lead_agent = create_lead_agent(model, checkpointer=InMemorySaver())

    result = await lead_agent.ainvoke(
      {"messages": [HumanMessage(content="write and run hello.py")]},
      config={"configurable": {"thread_id": "task-tool-test"}},
    )

    self.assertEqual(result["messages"][-1].text, "The delegated task completed.")
