"""Root Graph message extraction and ordered ingestion without persistence hooks."""

import unittest

from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolRuntime
from langgraph.types import Command
from runtime_fixtures import ToolModel
from shikigen.core.execution import ExecutionReason, RunExecution
from shikigen.core.graph_events import GraphEventAdapter
from shikigen.core.loop import execute_agent_loop
from test_loop import protocol


class GraphEventAdapterTests(unittest.TestCase):
  def test_repeated_values_and_tool_identity(self):
    adapter = GraphEventAdapter()
    messages = [
      HumanMessage(id="h", content="hi"),
      AIMessage(
        id="a", content="", tool_calls=[{"id": "call", "name": "work", "args": {}}]
      ),
      ToolMessage(id="temporary", tool_call_id="call", content="ok", artifact=None),
    ]
    values = protocol("values", {"messages": messages})
    result = adapter.messages(values)
    self.assertEqual([m["type"] for m in result], ["human", "ai", "tool"])
    self.assertEqual(result[-1]["message_id"], "tool-result:call")
    self.assertIn("artifact", result[-1])
    self.assertEqual(adapter.messages(values), [])
    with self.assertRaises(ValueError):
      adapter.messages(
        protocol("values", {"messages": [AIMessage(id="a", content="changed")]})
      )

  def test_child_graph_events_are_not_parent_messages(self):
    adapter = GraphEventAdapter()
    self.assertEqual(
      adapter.messages(
        protocol(
          "values",
          {"messages": [AIMessage(id="child", content="private")]},
          ["child:1"],
        )
      ),
      [],
    )
    self.assertIsNone(
      adapter.delta(
        protocol(
          "messages", [AIMessage(id="child", content="private"), {}], ["child:1"]
        )
      )
    )

  def test_standard_text_start_delta_and_finish(self):
    adapter = GraphEventAdapter()

    def event(data):
      return protocol("messages", [data, {}])

    self.assertIsNone(
      adapter.delta(event({"event": "message-start", "role": "ai", "id": "a"}))
    )
    first = adapter.delta(
      event({"event": "content-block-start", "content": {"type": "text", "text": "你"}})
    )
    second = adapter.delta(
      event(
        {"event": "content-block-delta", "delta": {"type": "text-delta", "text": "好"}}
      )
    )
    self.assertEqual(first, {"message_id": "a", "text": "你", "done": False})
    self.assertEqual(second["text"], "好")
    self.assertTrue(adapter.delta(event({"event": "message-finish"}))["done"])
    with self.assertRaises(ValueError):
      adapter.delta(
        event(
          {
            "event": "content-block-delta",
            "delta": {"type": "text-delta", "text": "late"},
          }
        )
      )


class GraphIngestionTests(unittest.IsolatedAsyncioTestCase):
  async def run_graph(self, graph):
    order = []

    async def delta(data):
      order.append(("delta", data))

    async def message(content):
      order.append(("message", content))
      return len(order)

    execution = RunExecution("run", "thread")
    outcome = await execute_agent_loop(
      graph,
      HumanMessage(id="entry", content="hi"),
      execution=execution,
      ingest_delta=delta,
      ingest_message=message,
    )
    return outcome, order

  async def test_streaming_model_deltas_precede_root_complete_message(self):
    agent = create_agent(FakeListChatModel(responses=["你好"]), tools=[])
    outcome, order = await self.run_graph(agent)
    self.assertEqual(outcome.reason, ExecutionReason.COMPLETED)
    deltas = [data for kind, data in order if kind == "delta"]
    answer = order[-1][1]
    self.assertEqual("".join(d["text"] for d in deltas), "你好")
    self.assertEqual({d["message_id"] for d in deltas}, {answer["message_id"]})
    self.assertEqual(AIMessage(content=answer["content"]).text, "你好")
    self.assertEqual(order[-1][0], "message")

  async def test_tool_command_result_is_extracted_from_root_state(self):
    @tool
    def command_tool(runtime: ToolRuntime) -> Command:
      """Return a tool result through a state update."""
      return Command(
        update={
          "messages": [ToolMessage(content="saved", tool_call_id=runtime.tool_call_id)]
        }
      )

    agent = create_agent(
      ToolModel(
        responses=[
          AIMessage(
            id="call",
            content="",
            tool_calls=[{"id": "tool-call", "name": "command_tool", "args": {}}],
          ),
          AIMessage(id="answer", content="done"),
        ]
      ),
      tools=[command_tool],
    )
    outcome, order = await self.run_graph(agent)
    self.assertEqual(outcome.reason, ExecutionReason.COMPLETED)
    messages = [data for kind, data in order if kind == "message"]
    self.assertEqual([m["type"] for m in messages], ["human", "ai", "tool", "ai"])
    self.assertEqual(messages[2]["content"], "saved")

  async def test_complete_message_is_ingested_before_later_node_failure(self):
    graph = StateGraph(MessagesState)
    graph.add_node(
      "answer", lambda state: {"messages": [AIMessage(id="answer", content="saved")]}
    )

    def fail(state):
      raise ValueError("later failure")

    graph.add_node("fail", fail)
    graph.add_edge(START, "answer")
    graph.add_edge("answer", "fail")
    graph.add_edge("fail", END)
    outcome, order = await self.run_graph(graph.compile())
    self.assertEqual(outcome.reason, ExecutionReason.FAILED)
    self.assertEqual(order[-1][1]["content"], "saved")
