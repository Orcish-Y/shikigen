import tempfile
import unittest
from pathlib import Path
from typing import Annotated, TypedDict
from unittest.mock import AsyncMock, patch

import httpx
from langchain.agents import create_agent
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph, add_messages
from langgraph.types import interrupt
from runtime_fixtures import ToolModel
from shikigen.app_config import AppConfig, DatabaseConfig, McpConfig, ModelConfig
from shikigen.execution import ExecutionOutcome, ExecutionPause, ExecutionReason
from shikigen.graph_pause import GraphPauseCollector
from shikigen.persistence import ChatStore
from shikigen.runtime.approval import build_approval_middleware
from shikigen.runtime.composition import assemble_runtime, open_runtime
from shikigen.runtime.run_state import ThreadBusy
from sse_fixtures import parse_sse_frames

from app.server import app


class State(TypedDict):
  messages: Annotated[list[AnyMessage], add_messages]


def payload(name):
  return {
    "action_requests": [
      {"name": name, "args": {"path": "example.txt"}, "description": "review"}
    ],
    "review_configs": [
      {"action_name": name, "allowed_decisions": ["approve", "reject"]}
    ],
  }


def nested_graph():
  def root(state):
    interrupt(payload("write_file"))
    return {}

  def child(state):
    interrupt(payload("bash"))
    return {}

  nested = StateGraph(State)
  nested.add_node("child", child)
  nested.add_edge(START, "child")
  nested.add_edge("child", END)
  graph = StateGraph(State)
  graph.add_node("root", root)
  graph.add_node("nested", nested.compile())
  for node in ("root", "nested"):
    graph.add_edge(START, node)
    graph.add_edge(node, END)
  return graph.compile(checkpointer=InMemorySaver())


class ApprovalPauseTests(unittest.IsolatedAsyncioTestCase):
  async def asyncSetUp(self):
    directory = tempfile.TemporaryDirectory()
    self.addCleanup(directory.cleanup)
    self.path = Path(directory.name) / "product.db"
    self.store = await ChatStore.open(self.path)
    self.addAsyncCleanup(self.store.close)

  def runtime(self, agent, store=None):
    runtime = assemble_runtime(
      config=AppConfig(model=ModelConfig(), mcp=McpConfig()),
      agent=agent,
      chat_store=store or self.store,
    )
    self.addAsyncCleanup(runtime.lifecycle.shutdown)
    return runtime

  async def test_real_policy_blocks_tools_and_rebuilds_over_http(self):
    calls = []

    @tool
    def write_file(path: str) -> str:
      """Write a file."""
      calls.append(path)
      return "written"

    @tool
    def bash(command: str) -> str:
      """Run a command."""
      calls.append(command)
      return "done"

    agent = create_agent(
      ToolModel(
        responses=[
          AIMessage(
            content="",
            tool_calls=[
              {"id": "write-1", "name": "write_file", "args": {"path": "a.txt"}},
              {"id": "bash-1", "name": "bash", "args": {"command": "echo hi"}},
            ],
          )
        ]
      ),
      tools=[write_file, bash],
      middleware=[build_approval_middleware(["write_file", "bash"])],
      checkpointer=InMemorySaver(),
    )
    runtime = self.runtime(agent)
    thread = await runtime.threads.create_thread()
    execution = await runtime.runs.start_run(thread, "do work")
    row = await runtime.runs.wait_run(execution)
    self.assertEqual(row["status"], "interrupted")
    self.assertEqual(calls, [])
    self.assertIsNone(row["completed_at"])
    self.assertIsNone(runtime.executions.get(thread, execution.run_id))
    with self.assertRaises(ThreadBusy):
      await runtime.runs.start_run(thread, "more")
    facts = await runtime.runs.list_run_events(thread, execution.run_id)
    required = facts[-2]
    self.assertEqual(required["event_type"], "approval_required")
    pending = required["content"]["interrupts"]
    self.assertEqual(len(pending), 1)
    self.assertEqual(len(pending[0]["value"]["action_requests"]), 2)
    self.assertEqual(
      pending[0]["value"]["review_configs"][0]["allowed_decisions"],
      ["approve", "reject"],
    )
    events = [event async for event in execution.stream.subscribe()]
    self.assertEqual([e.data for e in events if e.event == "durable_event"], facts)
    self.assertEqual(events[-1].data, {"status": "interrupted"})
    self.assertFalse(any(e.data == {"status": "completed"} for e in events))

    # 新连接、空执行注册表、无 Graph，仍能恢复全部审批内容。
    reopened = await ChatStore.open(self.path)
    self.addAsyncCleanup(reopened.close)
    restored = self.runtime(None, reopened)
    with patch.object(app.state, "runtime", restored, create=True):
      async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
      ) as client:
        url = f"/api/threads/{thread}/runs/{execution.run_id}/stream"
        first = await client.get(url)
        second = await client.get(url)
    self.assertEqual(first.status_code, 200)
    self.assertEqual(first.text, second.text)
    frames = parse_sse_frames(first.text)
    approval = [
      frame["data"]
      for frame in frames
      if frame["event"] == "event" and frame["data"]["category"] == "approval"
    ]
    self.assertEqual(approval[0]["event_type"], "required")
    self.assertEqual(approval[0]["payload"], required["content"])

  async def test_root_and_child_interrupts_use_exact_observed_checkpoint(self):
    agent = nested_graph()
    runtime = self.runtime(agent)
    thread = await runtime.threads.create_thread()
    with patch.object(agent, "aget_state", wraps=agent.aget_state) as read:
      execution = await runtime.runs.start_run(thread, "nested")
      self.assertEqual(
        (await runtime.runs.wait_run(execution))["status"], "interrupted"
      )
    facts = await runtime.runs.list_run_events(thread, execution.run_id)
    required = facts[-2]["content"]
    self.assertEqual(read.call_args.args[0], required["checkpoint"])
    self.assertTrue(read.call_args.kwargs["subgraphs"])
    pending = required["interrupts"]
    self.assertEqual(len(pending), 2)
    self.assertEqual(len({item["id"] for item in pending}), 2)
    self.assertEqual(sum(item["namespace"] == "" for item in pending), 1)
    self.assertEqual(
      {item["value"]["action_requests"][0]["name"] for item in pending},
      {"bash", "write_file"},
    )
    # 再写入一个更新 checkpoint，按保存的坐标读到的仍是本次暂停。
    await agent.aupdate_state({"configurable": {"thread_id": thread}}, {"messages": []})
    latest = await agent.aget_state({"configurable": {"thread_id": thread}})
    self.assertNotEqual(
      latest.config["configurable"]["checkpoint_id"],
      required["checkpoint"]["configurable"]["checkpoint_id"],
    )
    collector = GraphPauseCollector(thread)
    collector.checkpoint = required["checkpoint"]
    pause = await collector.read_pause(agent)
    self.assertEqual(list(pause.interrupts), pending)

  async def test_approval_and_status_rollback_together(self):
    await self.store.create_thread("thread")
    await self.store.create_run(
      thread_id="thread",
      run_id="run",
      entry_message=HumanMessage(id="human", content="hi"),
    )
    before = await self.store.list_run_events("thread", "run")
    outcome = ExecutionOutcome(
      ExecutionReason.INTERRUPTED,
      pause=ExecutionPause(
        checkpoint={
          "configurable": {
            "thread_id": "thread",
            "checkpoint_ns": "",
            "checkpoint_id": "cp",
          }
        },
        interrupts=({"id": "interrupt", "namespace": "", "value": payload("bash")},),
      ),
    )
    original = self.store._insert_fact

    async def fail_after_required(*args):
      if args[2] == "run_interrupted":
        raise OSError("disk failure")
      await original(*args)

    with patch.object(self.store, "_insert_fact", side_effect=fail_after_required):
      with self.assertRaises(OSError):
        await self.store.settle_execution(
          thread_id="thread", run_id="run", outcome=outcome
        )
    self.assertEqual((await self.store.get_run("run", "thread"))["status"], "running")
    self.assertEqual(await self.store.list_run_events("thread", "run"), before)
    result = await self.store.settle_execution(
      thread_id="thread", run_id="run", outcome=outcome
    )
    again = await self.store.settle_execution(
      thread_id="thread", run_id="run", outcome=outcome
    )
    self.assertEqual(result.events, again.events)
    self.assertFalse(again.changed)

  def test_policy_rejects_missing_tools(self):
    with self.assertRaisesRegex(ValueError, "bash"):
      build_approval_middleware(["write_file"])

  async def test_default_composition_installs_policy_on_actual_tool_registry(self):
    config = AppConfig(
      model=ModelConfig(), mcp=McpConfig(), database=DatabaseConfig(path=str(self.path))
    )
    with (
      patch(
        "shikigen.runtime.composition.load_mcp_tools", new=AsyncMock(return_value=[])
      ),
      patch(
        "shikigen.runtime.composition.create_lead_agent",
        new=AsyncMock(return_value=object()),
      ) as factory,
    ):
      async with open_runtime(config):
        options = factory.call_args.kwargs
        self.assertIn("bash", options["tool_registry"].names)
        self.assertIn("write_file", options["tool_registry"].names)
        self.assertEqual(len(options["middlewares"]), 1)
        self.assertIsNotNone(options["checkpointer"])

  async def test_missing_checkpoint_never_falls_back_to_latest(self):
    collector = GraphPauseCollector("thread")
    agent = AsyncMock()
    with self.assertRaisesRegex(ValueError, "root checkpoint"):
      await collector.read_pause(agent)
    agent.aget_state.assert_not_awaited()

  async def test_invalid_pause_is_not_committed(self):
    await self.store.create_thread("thread")
    await self.store.create_run(
      thread_id="thread", run_id="run", entry_message=HumanMessage(id="h", content="hi")
    )
    for coordinate, interrupts in (
      ({}, ({"id": "a", "namespace": "", "value": {}},)),
      (
        {
          "configurable": {
            "thread_id": "wrong",
            "checkpoint_ns": "",
            "checkpoint_id": "cp",
          }
        },
        ({"id": "a", "namespace": "", "value": {}},),
      ),
      (
        {
          "configurable": {
            "thread_id": "thread",
            "checkpoint_ns": "",
            "checkpoint_id": "cp",
          }
        },
        (),
      ),
    ):
      with self.subTest(coordinate=coordinate, interrupts=interrupts):
        with self.assertRaises(ValueError):
          await self.store.settle_execution(
            thread_id="thread",
            run_id="run",
            outcome=ExecutionOutcome(
              ExecutionReason.INTERRUPTED, pause=ExecutionPause(coordinate, interrupts)
            ),
          )
        self.assertEqual(
          (await self.store.get_run("run", "thread"))["status"], "running"
        )
        self.assertEqual(len(await self.store.list_run_events("thread", "run")), 2)
