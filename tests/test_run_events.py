import asyncio
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime_fixtures import deterministic_agent
from shikigen.app_config import AppConfig, DatabaseConfig, McpConfig, ModelConfig
from shikigen.core.stream import Stream
from shikigen.runtime.composition import open_runtime
from shikigen.runtime.run_events import RunEventIngestor
from shikigen.runtime.runs import RunTransitions


class RunEventTests(unittest.IsolatedAsyncioTestCase):
  async def asyncSetUp(self):
    directory = tempfile.TemporaryDirectory()
    self.addCleanup(directory.cleanup)
    self.path = Path(directory.name) / "chat.db"
    self.config = AppConfig(
      model=ModelConfig(),
      mcp=McpConfig(),
      database=DatabaseConfig(path=str(self.path)),
      checkpointer={"type": "sqlite", "path": str(self.path)},
    )

  async def test_every_published_fact_is_committed_and_matches_query(self):
    original = Stream.publish
    observed = []

    def publish(stream, event, data):
      if event == "durable_event":
        with sqlite3.connect(self.path) as reader:
          row = reader.execute(
            "SELECT seq, event_type FROM run_events WHERE id = ?", (data["id"],)
          ).fetchone()
        self.assertEqual(row, (data["seq"], data["event_type"]))
        observed.append(data)
      return original(stream, event, data)

    with patch(
      "shikigen.runtime.composition.create_lead_agent", new=deterministic_agent
    ):
      async with open_runtime(self.config) as runtime:
        thread = await runtime.threads.create_thread()
        with patch.object(Stream, "publish", publish):
          execution = await runtime.runs.start_run(thread, "add")
          await runtime.runs.wait_run(execution)
        facts = await runtime.runs.list_run_events(thread, execution.run_id)
        self.assertEqual(observed, facts)
        self.assertEqual(
          [fact["event_type"] for fact in facts],
          [
            "run_running",
            "human_message",
            "ai_message",
            "tool_message",
            "ai_message",
            "run_completed",
          ],
        )
        events = [event async for event in execution.stream.subscribe()]
        self.assertEqual([e.data for e in events if e.event == "durable_event"], facts)
        self.assertIsNone(runtime.executions.get(thread, execution.run_id))

  async def test_publication_failure_does_not_fail_graph_or_lose_committed_facts(self):
    original = Stream.publish
    for fail_type in ("run_running", "ai_message", "tool_message", "run_completed"):
      with self.subTest(fail_type=fail_type):

        def publish(stream, event, data, fail_type=fail_type):
          if event == "durable_event" and data["event_type"] == fail_type:
            raise OSError("broadcast unavailable")
          return original(stream, event, data)

        with patch(
          "shikigen.runtime.composition.create_lead_agent", new=deterministic_agent
        ):
          async with open_runtime(self.config) as runtime:
            thread = await runtime.threads.create_thread()
            with (
              patch.object(Stream, "publish", publish),
              self.assertLogs("shikigen.runtime.run_events"),
            ):
              execution = await runtime.runs.start_run(thread, "add")
              row = await runtime.runs.wait_run(execution)
            self.assertEqual(row["status"], "completed")
            facts = await runtime.runs.list_run_events(thread, execution.run_id)
            self.assertEqual(len(facts), 6)
            events = [event async for event in execution.stream.subscribe()]
            self.assertTrue(
              any(e.data == {"code": "event_publication_failed"} for e in events)
            )
            self.assertFalse(any(e.event == "error" for e in events))
            self.assertIsNone(runtime.executions.get(thread, execution.run_id))
        with patch(
          "shikigen.runtime.composition.create_lead_agent", new=deterministic_agent
        ):
          async with open_runtime(self.config) as reopened:
            self.assertEqual(
              await reopened.runs.list_run_events(thread, execution.run_id), facts
            )

  async def test_entire_observation_channel_failure_still_settles(self):
    # Only durable publication is broken; ephemeral Graph streaming still works.
    original = Stream.publish

    def publish(stream, event, data):
      if event in ("durable_event", "stream_failed", "status", "error"):
        raise OSError("observer disconnected")
      return original(stream, event, data)

    with patch(
      "shikigen.runtime.composition.create_lead_agent", new=deterministic_agent
    ):
      async with open_runtime(self.config) as runtime:
        thread = await runtime.threads.create_thread()
        with (
          patch.object(Stream, "publish", publish),
          self.assertLogs("shikigen.runtime.run_events"),
        ):
          execution = await runtime.runs.start_run(thread, "add")
          self.assertEqual(
            (await runtime.runs.wait_run(execution))["status"], "completed"
          )
        self.assertIsNone(runtime.executions.get(thread, execution.run_id))
        self.assertEqual(
          len(await runtime.runs.list_run_events(thread, execution.run_id)), 6
        )

  async def test_message_write_failure_does_not_publish_candidate_message(self):
    with patch(
      "shikigen.runtime.composition.create_lead_agent", new=deterministic_agent
    ):
      async with open_runtime(self.config) as runtime:
        thread = await runtime.threads.create_thread()
        with patch.object(
          runtime.chat_store,
          "append_committed_event",
          side_effect=OSError("disk failed"),
        ):
          execution = await runtime.runs.start_run(thread, "add")
          row = await runtime.runs.wait_run(execution)
        self.assertEqual(row["status"], "error")
        facts = await runtime.runs.list_run_events(thread, execution.run_id)
        self.assertEqual(
          [f["event_type"] for f in facts],
          ["run_running", "human_message", "run_error"],
        )
        events = [e async for e in execution.stream.subscribe()]
        self.assertEqual([e.data for e in events if e.event == "durable_event"], facts)

  async def test_failed_settlement_and_failed_notification_preserve_storage_error(self):
    original = Stream.publish

    def publish(stream, event, data):
      if event == "stream_failed":
        raise RuntimeError("notification unavailable")
      return original(stream, event, data)

    with patch(
      "shikigen.runtime.composition.create_lead_agent", new=deterministic_agent
    ):
      async with open_runtime(self.config) as runtime:
        thread = await runtime.threads.create_thread()
        with (
          patch.object(
            runtime.runs._transitions,
            "settle_execution",
            side_effect=OSError("disk failed"),
          ),
          patch.object(Stream, "publish", publish),
          self.assertLogs("shikigen.runtime", level="ERROR"),
        ):
          execution = await runtime.runs.start_run(thread, "add")
          with self.assertRaisesRegex(OSError, "disk failed"):
            await runtime.runs.wait_run(execution)
        self.assertEqual(
          (await runtime.runs.read_run(thread, execution.run_id))["status"], "running"
        )
        events = [event async for event in execution.stream.subscribe()]
        self.assertFalse(any(e.event in ("status", "error") for e in events))
        facts = await runtime.runs.list_run_events(thread, execution.run_id)
        self.assertEqual([e.data for e in events if e.event == "durable_event"], facts)
        self.assertIsNone(runtime.executions.get(thread, execution.run_id))

  async def test_message_replay_keeps_identity_and_conflict_is_not_broadcast(self):
    from langchain_core.messages import HumanMessage
    from shikigen.contracts.runs import MessageConflict
    from shikigen.core.execution import RunExecution

    with patch(
      "shikigen.runtime.composition.create_lead_agent", new=deterministic_agent
    ):
      async with open_runtime(self.config) as runtime:
        thread = await runtime.threads.create_thread()
        await RunTransitions(runtime.chat_store).create_run(
          thread_id=thread,
          run_id="run",
          entry_message=HumanMessage(id="human", content="hello"),
        )
        execution = RunExecution(run_id="run", thread_id=thread)
        runtime.executions.install(execution)
        ingestor = RunEventIngestor(runtime.chat_store, runtime.executions)
        kwargs = dict(
          thread_id=thread,
          run_id="run",
          event_type="ai_message",
          category="message",
          event_key="ai:answer",
          content={
            "type": "ai",
            "message_id": "answer",
            "content": "ok",
            "tool_calls": [],
          },
        )
        first, second = await asyncio.gather(
          ingestor.append_event(**kwargs), ingestor.append_event(**kwargs)
        )
        self.assertEqual(first, second)
        with self.assertRaises(MessageConflict):
          await ingestor.append_event(
            **{**kwargs, "content": {**kwargs["content"], "content": "different"}}
          )
        execution.stream.close()
        events = [e async for e in execution.stream.subscribe()]
        self.assertEqual(len(events), 1)
        self.assertEqual(len(await runtime.runs.list_run_events(thread, "run")), 3)
