import unittest
from typing import Any

from langchain.agents.middleware import ToolCallRequest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.prebuilt import ToolRuntime
from langgraph.runtime import Runtime
from langgraph.types import Command
from shikigen.middleware.chat_persistence_middleware import ChatPersistenceMiddleware
from shikigen.middleware.tool_error_handling_middleware import (
  ToolErrorHandlingMiddleware,
)
from shikigen.runtime_context import AgentRunContext


class RecordingJournal:
  def __init__(self):
    self.events: list[dict[str, Any]] = []

  async def append_event(self, **event: Any) -> int:
    self.events.append(event)
    return len(self.events)


class ChatPersistenceMiddlewareTests(unittest.IsolatedAsyncioTestCase):
  def setUp(self) -> None:
    self.journal = RecordingJournal()
    self.middleware = ChatPersistenceMiddleware(self.journal)
    self.context = AgentRunContext(thread_id="thread-1", run_id="run-1")
    self.runtime = Runtime(context=self.context)
    self.tool_runtime: ToolRuntime[Any] = ToolRuntime(
      state={"messages": []},
      context=self.context,
      config={},
      stream_writer=lambda _: None,
      tool_call_id="call-1",
      store=None,
    )

  async def test_persists_the_current_human_message_before_agent(self) -> None:
    message = HumanMessage(id="human-1", content="hello")

    await self.middleware.abefore_agent(
      {"messages": [message]},
      self.runtime,
    )

    self.assertEqual(self.journal.events[0]["event_type"], "human_message")
    self.assertEqual(self.journal.events[0]["event_key"], "human:human-1")
    self.assertEqual(self.journal.events[0]["content"]["content"], "hello")

  async def test_persists_complete_ai_message_after_model(self) -> None:
    message = AIMessage(
      id="ai-1",
      content="complete answer",
      tool_calls=[{"id": "call-1", "name": "add", "args": {"a": 1}}],
    )

    await self.middleware.aafter_model(
      {"messages": [message]},
      self.runtime,
    )

    event = self.journal.events[0]
    self.assertEqual(event["event_type"], "ai_message")
    self.assertEqual(event["event_key"], "ai:ai-1")
    self.assertEqual(event["content"]["content"], "complete answer")
    self.assertEqual(event["content"]["tool_calls"][0]["id"], "call-1")

  async def test_persists_tool_message_after_tool_returns(self) -> None:
    request = ToolCallRequest(
      tool_call={"id": "call-1", "name": "add", "args": {"a": 1}},
      tool=None,
      state={"messages": []},
      runtime=self.tool_runtime,
    )

    async def execute(_request: ToolCallRequest) -> ToolMessage:
      return ToolMessage(
        content="2",
        name="add",
        tool_call_id="call-1",
      )

    result = await self.middleware.awrap_tool_call(request, execute)

    self.assertIsInstance(result, ToolMessage)
    event = self.journal.events[0]
    self.assertEqual(event["event_type"], "tool_message")
    self.assertEqual(event["event_key"], "tool:call-1")
    self.assertEqual(event["content"]["tool_call_id"], "call-1")

  async def test_persists_tool_message_returned_inside_command(self) -> None:
    request = ToolCallRequest(
      tool_call={"id": "call-1", "name": "add", "args": {"a": 1}},
      tool=None,
      state={"messages": []},
      runtime=self.tool_runtime,
    )
    tool_message = ToolMessage(content="2", tool_call_id="call-1")

    async def execute(_request: ToolCallRequest) -> Command:
      return Command(update={"messages": [tool_message]})

    result = await self.middleware.awrap_tool_call(request, execute)

    self.assertIsInstance(result, Command)
    self.assertEqual(self.journal.events[0]["event_key"], "tool:call-1")

  async def test_persists_tool_error_created_by_inner_middleware(self) -> None:
    request = ToolCallRequest(
      tool_call={"id": "call-1", "name": "add", "args": {"a": 1}},
      tool=None,
      state={"messages": []},
      runtime=self.tool_runtime,
    )
    error_middleware = ToolErrorHandlingMiddleware()

    async def fail(_request: ToolCallRequest) -> ToolMessage:
      raise ValueError("broken tool")

    async def handle_error(
      tool_request: ToolCallRequest,
    ) -> ToolMessage | Command[Any]:
      return await error_middleware.awrap_tool_call(tool_request, fail)

    result = await self.middleware.awrap_tool_call(request, handle_error)

    self.assertIsInstance(result, ToolMessage)
    assert isinstance(result, ToolMessage)
    self.assertEqual(result.status, "error")
    self.assertEqual(self.journal.events[0]["content"]["status"], "error")
