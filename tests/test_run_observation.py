import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from langchain_core.messages import HumanMessage
from shikigen.app_config import AppConfig, McpConfig, ModelConfig
from shikigen.execution import ExecutionOutcome, ExecutionReason, RunExecution
from test_loop import MessageAgent

from app.composition import assemble_runtime
from app.persistence import ChatStore
from app.run_events import RunEventIngestor
from app.run_state import ObservationUnavailable, RunNotFound


class ObservationTests(unittest.IsolatedAsyncioTestCase):
  async def asyncSetUp(self):
    directory = tempfile.TemporaryDirectory()
    self.addCleanup(directory.cleanup)
    self.path = Path(directory.name) / "runs.db"
    self.store = await ChatStore.open(self.path)
    self.addAsyncCleanup(self.store.close)
    self.runtime = assemble_runtime(
      config=AppConfig(model=ModelConfig(), mcp=McpConfig()),
      agent=MessageAgent(),
      chat_store=self.store,
    )
    self.addAsyncCleanup(self.runtime.lifecycle.shutdown)
    self.thread = await self.runtime.threads.create_thread()

  async def active(self):
    created = await self.store.create_run(
      thread_id=self.thread,
      run_id="run",
      entry_message=HumanMessage(id="human", content="hi"),
    )
    execution = RunExecution(
      "run", self.thread, replay_start_seq=created.events[0]["seq"]
    )
    self.runtime.executions.install(execution)
    RunEventIngestor.publish(execution.stream, created.events)
    return execution

  async def finish(self, execution):
    settled = await self.store.settle_execution(
      thread_id=self.thread,
      run_id="run",
      outcome=ExecutionOutcome(ExecutionReason.COMPLETED),
    )
    RunEventIngestor.publish(execution.stream, settled.events, settlement=settled)
    execution.stream.close()
    self.runtime.executions.remove(execution)

  async def test_history_read_race_with_deltas_commit_close_and_removal(self):
    execution = await self.active()
    entered, release = asyncio.Event(), asyncio.Event()
    original = self.store.list_run_events

    async def blocked(*args):
      entered.set()
      await release.wait()
      return await original(*args)

    with patch.object(self.store, "list_run_events", side_effect=blocked):
      opening = asyncio.create_task(self.runtime.runs.observe_run(self.thread, "run"))
      await entered.wait()
      self.assertEqual(len(execution.stream._subscribers), 1)
      ingestor = RunEventIngestor(self.store, self.runtime.executions)
      for _ in range(100):
        await ingestor.ingest_delta(
          {"message_id": "answer", "text": "a", "done": False},
          thread_id=self.thread,
          run_id="run",
        )
      await ingestor.ingest_message(
        {"type": "ai", "message_id": "answer", "content": "a" * 100, "tool_calls": []},
        thread_id=self.thread,
        run_id="run",
      )
      await self.finish(execution)
      release.set()
      observation = await opening
    events = [event async for event in observation]
    facts = [e.data for e in events if e.event == "durable_event"]
    self.assertEqual(facts, await original(self.thread, "run"))
    self.assertEqual(sum(e.event == "message" for e in events), 100)
    self.assertEqual(events[-1].data, {"status": "completed"})
    self.assertEqual(len(execution.stream._subscribers), 0)
    # 同 seq 的完整事实替换所有预览；重建只剩完整事实。
    rebuilt = await self.runtime.runs.observe_run(self.thread, "run")
    self.assertEqual([e.data async for e in rebuilt], facts)

  async def test_two_observers_and_close_before_iteration(self):
    execution = await self.active()
    one = await self.runtime.runs.observe_run(self.thread, "run")
    two = await self.runtime.runs.observe_run(self.thread, "run")
    await one.aclose()
    await one.aclose()
    self.assertEqual(len(execution.stream._subscribers), 1)
    self.assertFalse(execution.abort_event.is_set())
    await self.finish(execution)
    facts = [e.data async for e in two if e.event == "durable_event"]
    self.assertEqual(facts, await self.store.list_run_events(self.thread, "run"))

  async def test_read_failure_and_cancel_release_subscription(self):
    execution = await self.active()
    for error in (OSError("read failed"), asyncio.CancelledError()):
      with patch.object(self.store, "list_run_events", side_effect=error):
        with self.assertRaises(type(error)):
          await self.runtime.runs.observe_run(self.thread, "run")
      self.assertEqual(len(execution.stream._subscribers), 0)
      self.assertFalse(execution.abort_event.is_set())

  async def test_missing_execution_and_wrong_thread(self):
    execution = await self.active()
    self.runtime.executions.remove(execution)
    with self.assertRaises(ObservationUnavailable):
      await self.runtime.runs.observe_run(self.thread, "run")
    with self.assertRaises(RunNotFound):
      await self.runtime.runs.observe_run("other", "run")
    self.assertEqual(
      (await self.store.get_run("run", self.thread))["status"], "running"
    )

  async def test_completion_between_run_lookup_and_registry_lookup(self):
    execution = await self.active()
    original = self.runtime.runs.read_run

    async def read(*args):
      row = await original(*args)
      if self.runtime.executions.get(self.thread, "run") is not None:
        await self.finish(execution)
      return row

    with patch.object(self.runtime.runs, "read_run", side_effect=read):
      observation = await self.runtime.runs.observe_run(self.thread, "run")
    self.assertEqual(observation.run["status"], "completed")
    self.assertEqual(
      [e.data async for e in observation],
      await self.store.list_run_events(self.thread, "run"),
    )

  async def test_persistent_prefix_is_not_replayed_from_invocation_cache(self):
    execution = await self.active()
    # 模拟后续 invocation：早先事实只在数据库，本次缓存从新边界开始。
    prefix = await self.store.list_run_events(self.thread, "run")
    self.runtime.executions.remove(execution)
    execution = RunExecution("run", self.thread, replay_start_seq=prefix[-1]["seq"] + 1)
    self.runtime.executions.install(execution)
    observation = await self.runtime.runs.observe_run(self.thread, "run")
    await self.finish(execution)
    self.assertEqual(
      [e.data async for e in observation if e.event == "durable_event"],
      await self.store.list_run_events(self.thread, "run"),
    )

  async def test_real_execution_reconnect_never_calls_graph_again(self):
    agent = self.runtime.runs.agent
    with patch.object(agent, "astream_events", wraps=agent.astream_events) as calls:
      execution = await self.runtime.runs.start_run(self.thread, "hi")
      observation = await self.runtime.runs.observe_run(self.thread, execution.run_id)
      await observation.aclose()
      observation = await self.runtime.runs.observe_run(self.thread, execution.run_id)
      async for _ in observation:
        pass
      await self.runtime.runs.wait_run(execution)
      first = await self.runtime.runs.observe_run(self.thread, execution.run_id)
      second = await self.runtime.runs.observe_run(self.thread, execution.run_id)
      self.assertEqual([e.data async for e in first], [e.data async for e in second])
      self.assertEqual(calls.call_count, 1)

  async def test_all_settled_states_rebuild_after_reopen(self):
    from shikigen.execution import ExecutionPause

    for reason in ExecutionReason:
      with self.subTest(reason=reason):
        thread = await self.runtime.threads.create_thread()
        await self.store.create_run(
          thread_id=thread,
          run_id=reason.value,
          entry_message=HumanMessage(id=reason.value, content="hi"),
        )
        await self.store.settle_execution(
          thread_id=thread,
          run_id=reason.value,
          outcome=ExecutionOutcome(
            reason,
            error=ValueError("failed") if reason is ExecutionReason.FAILED else None,
            pause=ExecutionPause(checkpoint={}, interrupts=())
            if reason is ExecutionReason.INTERRUPTED
            else None,
          ),
        )
        reopened = await ChatStore.open(self.path)
        try:
          with patch.object(self.runtime.runs, "_store", reopened):
            observation = await self.runtime.runs.observe_run(thread, reason.value)
            facts = [e.data async for e in observation]
          self.assertEqual(facts[-1]["content"]["status"], observation.run["status"])
        finally:
          await reopened.close()
