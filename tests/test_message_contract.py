"""第 5 步：真实 checkpoint、多轮归属、重放和 SSE 契约。"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import START, MessagesState, StateGraph
from langgraph.types import Command, interrupt
from pydantic import ValidationError
from runtime_fixtures import ToolModel, add
from shikigen.app_config import AppConfig, DatabaseConfig, McpConfig, ModelConfig
from shikigen.contracts.messages import message_content, normalize_message
from shikigen.contracts.runs import MessageConflict
from shikigen.contracts.stream import StreamEvent
from shikigen.core.context import AgentRunContext
from shikigen.core.execution import (
  ExecutionOutcome,
  ExecutionReason,
  ExecutionRegistry,
  RunExecution,
)
from shikigen.core.graph_events import GraphEventAdapter
from shikigen.persistence import ChatStore
from shikigen.runtime.composition import open_runtime
from shikigen.runtime.run_events import RunEventIngestor
from shikigen.runtime.runs import RunTransitions
from sse_fixtures import parse_sse

from app.routes.run import stream_run_events
from app.run_contract import SSE_EVENT, RunSseEncoder


async def two_round_agent(*, config, middlewares, checkpointer, tool_registry):
  responses = []
  for round_id in (1, 2):
    responses.extend(
      [
        AIMessage(
          id=f"ai-call-{round_id}",
          content="",
          tool_calls=[
            {"id": f"call-{round_id}", "name": "add", "args": {"a": round_id, "b": 2}}
          ],
        ),
        AIMessage(id=f"answer-{round_id}", content=str(round_id + 2)),
      ]
    )
  return create_agent(
    ToolModel(responses=responses),
    tools=[add],
    middleware=middlewares,
    context_schema=AgentRunContext,
    checkpointer=checkpointer,
  )


class MessageContractTests(unittest.IsolatedAsyncioTestCase):
  async def asyncSetUp(self):
    temp = tempfile.TemporaryDirectory()
    self.addCleanup(temp.cleanup)
    self.path = Path(temp.name) / "chat.db"
    self.store = await ChatStore.open(self.path)
    self.addAsyncCleanup(self.store.close)
    await self.store.create_thread("thread")
    await RunTransitions(self.store).create_run(
      thread_id="thread",
      run_id="first",
      entry_message=HumanMessage(id="entry", content="hi"),
    )

  async def test_history_replay_retains_owner_and_conflicting_history_fails(self):
    message = message_content(AIMessage(id="answer", content="original"))
    original = await self.store.append_message(
      thread_id="thread", run_id="first", content=message
    )
    await RunTransitions(self.store).settle_execution(
      thread_id="thread",
      run_id="first",
      outcome=ExecutionOutcome(ExecutionReason.COMPLETED),
    )
    with self.assertRaises(MessageConflict):
      await RunTransitions(self.store).create_run(
        thread_id="thread",
        run_id="second",
        entry_message=HumanMessage(id="entry", content="hi"),
      )
    self.assertIsNone(await self.store.get_run("second", "thread"))
    await RunTransitions(self.store).create_run(
      thread_id="thread",
      run_id="second",
      entry_message=HumanMessage(id="entry-2", content="next"),
    )
    registry = ExecutionRegistry()
    execution = RunExecution(run_id="second", thread_id="thread")
    registry.install(execution)
    journal = RunEventIngestor(self.store, registry)
    for _ in range(2):
      seq = await journal.append_event(
        thread_id="thread",
        run_id="second",
        category="message",
        event_type="ai_message",
        event_key="ai:answer",
        content=message,
      )
      self.assertEqual(seq, original.event["seq"])
    with self.assertRaises(MessageConflict):
      await self.store.append_message(
        thread_id="thread", run_id="second", content={**message, "content": "changed"}
      )
    execution.stream.close()
    self.assertEqual([e async for e in execution.stream.subscribe()], [])
    self.assertEqual(len(await self.store.list_messages_by_run("thread", "second")), 1)

  async def test_tool_identity_ignores_framework_id_but_preserves_artifact_presence(
    self,
  ):
    first = message_content(
      ToolMessage(id="transient-1", tool_call_id="call", content="ok")
    )
    second = message_content(
      ToolMessage(id="transient-2", tool_call_id="call", content="ok")
    )
    self.assertEqual(first, second)
    self.assertEqual(first["message_id"], "tool-result:call")
    self.assertNotIn("artifact", first)
    original = await self.store.append_message(
      thread_id="thread", run_id="first", content=first
    )
    replay = await self.store.append_message(
      thread_id="thread", run_id="first", content=second
    )
    self.assertEqual(original.event, replay.event)
    with self.assertRaises(MessageConflict):
      await self.store.append_message(
        thread_id="thread", run_id="first", content={**second, "artifact": None}
      )

  async def test_two_checkpointed_rounds_have_separate_facts_and_stable_preview_ids(
    self,
  ):
    config = AppConfig(
      model=ModelConfig(),
      mcp=McpConfig(),
      database=DatabaseConfig(path=str(self.path)),
      checkpointer={"type": "sqlite", "path": str(self.path)},
    )
    with patch("shikigen.runtime.composition.create_lead_agent", new=two_round_agent):
      async with open_runtime(config) as runtime:
        thread = await runtime.threads.create_thread()
        histories = []
        for round_id in (1, 2):
          execution = await runtime.runs.start_run(thread, f"round {round_id}")
          self.assertEqual(
            (await runtime.runs.wait_run(execution))["status"], "completed"
          )
          facts = await runtime.runs.list_run_messages(thread, execution.run_id)
          self.assertEqual(len(facts), 4)
          self.assertTrue(all(f["run_id"] == execution.run_id for f in facts))
          histories.append(facts)
          events = [e async for e in execution.stream.subscribe()]
          encoder = RunSseEncoder("thread", "first")
          for event in events:
            if frame := encoder.encode(event):
              SSE_EVENT.validate_python(parse_sse(frame))
          previews = [
            e.data for e in events if e.event == "message" and not e.data["done"]
          ]
          self.assertTrue(previews)
          answer = next(
            f for f in facts if f["content"]["message_id"] == f"answer-{round_id}"
          )
          self.assertEqual({p["seq"] for p in previews}, {answer["seq"]})
          complete_index = next(
            i
            for i, e in enumerate(events)
            if e.event == "durable_event" and e.data["seq"] == answer["seq"]
          )
          self.assertTrue(
            all(
              i < complete_index
              for i, e in enumerate(events)
              if e.event == "message" and not e.data["done"]
            )
          )
          self.assertEqual({p["message_id"] for p in previews}, {f"answer-{round_id}"})
          tools = [
            e.data["content"]
            for e in events
            if e.event == "durable_event"
            and e.data["category"] == "message"
            and e.data["content"]["type"] == "tool"
          ]
          self.assertEqual(len(tools), 1)
          self.assertEqual(tools[0]["message_id"], f"tool-result:call-{round_id}")
        self.assertTrue(
          {f["seq"] for f in histories[0]}.isdisjoint(f["seq"] for f in histories[1])
        )
        snapshot = await runtime.agent.aget_state(
          {"configurable": {"thread_id": thread}}
        )
        self.assertEqual(len(snapshot.values["messages"]), 8)

  async def test_same_run_checkpoint_resume_replay_returns_existing_fact(self):
    async def node(state):
      interrupt("continue")
      return {
        "messages": [AIMessage(id="after-pause", content="persisted after interrupt")]
      }

    graph = StateGraph(MessagesState)
    graph.add_node("node", node)
    graph.add_edge(START, "node")
    agent = graph.compile(checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "thread"}}
    registry = ExecutionRegistry()
    execution = RunExecution(run_id="first", thread_id="thread")
    registry.install(execution)
    ingestor = RunEventIngestor(self.store, registry)

    async def consume(value):
      adapter = GraphEventAdapter()
      async with await agent.astream_events(
        value, config=config, version="v3"
      ) as events:
        async for event in events:
          for content in adapter.messages(event):
            await ingestor.ingest_message(content, thread_id="thread", run_id="first")

    await consume({"messages": [HumanMessage(id="entry", content="hi")]})
    await consume(Command(resume=True))
    before = await self.store.list_messages_by_run("thread", "first")
    await consume(None)
    self.assertEqual(await self.store.list_messages_by_run("thread", "first"), before)
    execution.stream.close()
    facts = [
      e async for e in execution.stream.subscribe() if e.event == "durable_event"
    ]
    self.assertEqual(len(facts), 1)

  def test_contract_rejects_unknown_fields_and_separates_preview_and_facts(self):
    with self.assertRaises(ValidationError):
      normalize_message(
        {"type": "ai", "message_id": "a", "content": "x", "tool_calls": [], "typo": 1}
      )
    encoder = RunSseEncoder("thread", "first")
    for event, data in (
      ("unknown", {}),
      ("message", {"text": "x", "done": True}),
      ("stream_failed", {"code": "lost", "status": "completed"}),
    ):
      with self.assertRaises(ValidationError):
        encoder.encode(StreamEvent(id="1", event=event, data=data))
    preview = parse_sse(
      encoder.encode(
        StreamEvent(
          id="2",
          event="message",
          data={"text": "draft", "done": False, "message_id": "answer", "seq": 3},
        )
      )
    )
    self.assertEqual(preview["data"]["message_id"], "answer")
    failure = parse_sse(
      encoder.encode(StreamEvent(id="3", event="stream_failed", data={"code": "lost"}))
    )
    self.assertEqual(failure["event"], "error")

  async def test_invalid_observation_ends_subscription_without_changing_run(self):
    execution = RunExecution(run_id="first", thread_id="thread")
    execution.stream.publish("message", {"text": "invalid end", "done": True})
    frames = [parse_sse(frame) async for frame in stream_run_events(execution)]
    self.assertEqual(
      frames[1:],
      [
        {
          "event": "error",
          "data": {
            "code": "invalid_event",
            "message": "Observation failed; read persisted run facts.",
            "recoverable": True,
          },
        }
      ],
    )
    self.assertFalse(execution.stream._subscribers)
    self.assertEqual((await self.store.get_run("first", "thread"))["status"], "running")

  async def test_complete_fact_corrects_preview_and_replay_has_one_identity(self):
    complete = await self.store.append_message(
      thread_id="thread",
      run_id="first",
      content=message_content(AIMessage(id="answer", content="corrected")),
    )
    encoder = RunSseEncoder("thread", "first")
    frames = [
      StreamEvent(
        id="1",
        event="message",
        data={"text": "draft", "done": False, "message_id": "answer", "seq": 3},
      ),
      StreamEvent(id="2", event="durable_event", data=complete.event),
      StreamEvent(id="3", event="durable_event", data=complete.event),
    ]
    # 一个最小消费者 fixture：完整事实按身份覆盖预览，重复事实无新增消息。
    projection = {}
    for event in frames:
      frame = parse_sse(encoder.encode(event))
      SSE_EVENT.validate_python(frame)
      if frame["event"] == "delta":
        data = frame["data"]
        projection[data["seq"]] = data["value"]
      else:
        data = frame["data"]
        projection[data["seq"]] = data["payload"]["content"]
    self.assertEqual(projection, {complete.event["seq"]: "corrected"})
