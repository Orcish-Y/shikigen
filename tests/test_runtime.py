import asyncio
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from langchain.agents.middleware import HumanInTheLoopMiddleware
from langchain_core.messages import HumanMessage
from runtime_fixtures import deterministic_agent
from shikigen.app_config import AppConfig, DatabaseConfig, McpConfig, ModelConfig
from shikigen.execution import ExecutionOutcome, ExecutionReason
from test_loop import BlockingAgent, FailingAgent, MessageAgent

from app.composition import assemble_runtime, open_runtime
from app.persistence import ChatStore
from app.run_state import ExecutionStopped, RunNotFound, ThreadBusy, ThreadNotFound


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
  async def asyncSetUp(self):
    self.directory = tempfile.TemporaryDirectory()
    self.addCleanup(self.directory.cleanup)
    self.path = Path(self.directory.name) / "runs.db"
    self.store = await ChatStore.open(self.path)
    self.addAsyncCleanup(self.store.close)
    self.runtime = assemble_runtime(
      config=AppConfig(model=ModelConfig(), mcp=McpConfig()),
      agent=MessageAgent(),
      chat_store=self.store,
    )
    self.addAsyncCleanup(self.runtime.lifecycle.shutdown)
    self.thread_id = await self.runtime.threads.create_thread(
      user_id="user", title="title"
    )

  async def test_unobserved_run_commits_and_remains_readable_after_removal(self):
    execution = await self.runtime.runs.start_run(self.thread_id, "hello")
    row = await self.runtime.runs.wait_run(execution)
    self.assertEqual(row["status"], "completed")
    self.assertIsNone(self.runtime.executions.get(self.thread_id, execution.run_id))
    self.assertEqual(await self.runtime.runs.wait_run(execution), row)
    messages = await self.runtime.runs.list_run_messages(
      self.thread_id, execution.run_id
    )
    self.assertEqual([m["content"]["content"] for m in messages], ["hello"])
    facts = await self.runtime.runs.list_run_events(self.thread_id, execution.run_id)
    self.assertEqual(
      [f["event_type"] for f in facts],
      [
        "run_running",
        "human_message",
        "run_completed",
      ],
    )
    threads = await self.runtime.threads.list_threads()
    self.assertEqual((threads[0]["user_id"], threads[0]["title"]), ("user", "title"))

  async def test_waiter_cancellation_does_not_stop_execution_or_settlement(self):
    entered, release = asyncio.Event(), asyncio.Event()
    original = self.store.settle_execution

    async def settle(**kwargs):
      entered.set()
      await release.wait()
      return await original(**kwargs)

    with patch.object(self.store, "settle_execution", side_effect=settle):
      execution = await self.runtime.runs.start_run(self.thread_id, "hello")
      waiter = asyncio.create_task(self.runtime.runs.wait_run(execution))
      await asyncio.wait_for(entered.wait(), 2)
      waiter.cancel()
      with self.assertRaises(asyncio.CancelledError):
        await waiter
      self.assertFalse(execution.task.done())
      self.assertFalse(execution.abort_event.is_set())
      self.assertEqual(
        (await self.runtime.runs.read_run(self.thread_id, execution.run_id))["status"],
        "running",
      )
      release.set()
      self.assertEqual(
        (await self.runtime.runs.wait_run(execution))["status"], "completed"
      )

  async def test_cancelled_start_caller_does_not_leave_a_committed_orphan(self):
    entered, release = asyncio.Event(), asyncio.Event()
    original = self.store.create_run

    async def create(**kwargs):
      result = await original(**kwargs)
      entered.set()
      await release.wait()
      return result

    with patch.object(self.store, "create_run", side_effect=create):
      starter = asyncio.create_task(
        self.runtime.runs.start_run(self.thread_id, "hello")
      )
      await asyncio.wait_for(entered.wait(), 2)
      starter.cancel()
      with self.assertRaises(asyncio.CancelledError):
        await starter
      operations = tuple(self.runtime.lifecycle._operations)
      release.set()
      execution = (await asyncio.gather(*operations))[0]
      self.assertEqual(
        (await self.runtime.runs.wait_run(execution))["status"], "completed"
      )

  async def test_settlement_failure_is_reported_to_waiter_and_observer(self):
    with (
      patch.object(self.store, "settle_execution", side_effect=OSError("disk failed")),
      self.assertLogs("app.run_execution", level="ERROR"),
    ):
      execution = await self.runtime.runs.start_run(self.thread_id, "hello")
      with self.assertRaisesRegex(OSError, "disk failed"):
        await self.runtime.runs.wait_run(execution)
    events = [event async for event in execution.stream.subscribe()]
    self.assertEqual(events[-1].event, "stream_failed")
    self.assertFalse(any(e.event in ("status", "error") for e in events))
    self.assertEqual(
      (await self.runtime.runs.read_run(self.thread_id, execution.run_id))["status"],
      "running",
    )

  async def test_graph_error_is_a_committed_product_result(self):
    self.runtime.runs.agent = FailingAgent()
    execution = await self.runtime.runs.start_run(self.thread_id, "hello")
    row = await self.runtime.runs.wait_run(execution)
    self.assertEqual(row["status"], "error")
    self.assertIn("stream setup failed", row["error"])

  async def test_shutdown_does_not_pretend_to_commit_user_cancellation(self):
    self.runtime.runs.agent = BlockingAgent()
    execution = await self.runtime.runs.start_run(self.thread_id, "hello")
    await self.runtime.lifecycle.shutdown()
    await self.runtime.lifecycle.shutdown()
    with self.assertRaises(ExecutionStopped):
      await self.runtime.runs.wait_run(execution)
    self.assertEqual(
      (await self.runtime.runs.read_run(self.thread_id, execution.run_id))["status"],
      "running",
    )
    self.assertIsNone(self.runtime.executions.get(self.thread_id, execution.run_id))
    with self.assertRaisesRegex(RuntimeError, "shutting down"):
      await self.runtime.runs.start_run(self.thread_id, "again")

  async def test_application_errors_do_not_depend_on_http(self):
    with self.assertRaises(ThreadNotFound):
      await self.runtime.runs.start_run("missing", "hello")
    with self.assertRaises(RunNotFound):
      await self.runtime.runs.read_run(self.thread_id, "missing")
    self.runtime.runs.agent = BlockingAgent()
    execution = await self.runtime.runs.start_run(self.thread_id, "hello")
    with self.assertRaises(ThreadBusy):
      await self.runtime.runs.start_run(self.thread_id, "again")
    with self.assertRaises(RunNotFound):
      await self.runtime.runs.read_run("other", execution.run_id)


class TransactionTests(unittest.IsolatedAsyncioTestCase):
  async def asyncSetUp(self):
    self.directory = tempfile.TemporaryDirectory()
    self.addCleanup(self.directory.cleanup)
    path = Path(self.directory.name) / "runs.db"
    self.first = await ChatStore.open(path)
    self.addAsyncCleanup(self.first.close)
    self.second = await ChatStore.open(path)
    self.addAsyncCleanup(self.second.close)
    await self.first.create_thread("thread")

  async def create(self, store, run_id):
    await store.create_run(
      thread_id="thread",
      run_id=run_id,
      entry_message=HumanMessage(id=f"human:{run_id}", content="hello"),
    )

  async def test_two_connections_cannot_create_two_active_runs(self):
    results = await asyncio.gather(
      self.create(self.first, "first"),
      self.create(self.second, "second"),
      return_exceptions=True,
    )
    self.assertEqual(sum(isinstance(r, ThreadBusy) for r in results), 1)
    self.assertEqual(sum(r is None for r in results), 1)

  async def test_creation_failure_and_cancellation_roll_back_all_facts(self):
    for error in (OSError("disk failed"), asyncio.CancelledError()):
      with self.subTest(error=type(error)):
        original = self.first._insert_fact
        count = 0

        async def insert(*args, original=original, error=error):
          nonlocal count
          count += 1
          await original(*args)
          if count == 2:
            raise error

        with patch.object(self.first, "_insert_fact", side_effect=insert):
          with self.assertRaises(type(error)):
            await self.create(self.first, "run")
        self.assertIsNone(await self.second.get_run("run", "thread"))
        self.assertEqual(await self.second.list_thread_messages("thread"), [])
    await self.create(self.first, "run")

  async def test_first_committed_terminal_wins_and_is_not_duplicated(self):
    for first_reason, second_reason in (
      (ExecutionReason.ABORTED, ExecutionReason.COMPLETED),
      (ExecutionReason.COMPLETED, ExecutionReason.ABORTED),
    ):
      run_id = str(first_reason)
      await self.create(self.first, run_id)
      first = await self.first.settle_execution(
        thread_id="thread",
        run_id=run_id,
        outcome=ExecutionOutcome(first_reason),
      )
      second = await self.second.settle_execution(
        thread_id="thread",
        run_id=run_id,
        outcome=ExecutionOutcome(second_reason),
      )
      self.assertEqual(first, second)
      facts = await self.first.list_run_events("thread", run_id)
      self.assertEqual(len(facts), 3)

  async def test_failed_settlement_rolls_back_state_and_lifecycle(self):
    await self.create(self.first, "run")
    with patch.object(self.first, "_insert_fact", side_effect=OSError("disk failed")):
      with self.assertRaises(OSError):
        await self.first.settle_execution(
          thread_id="thread",
          run_id="run",
          outcome=ExecutionOutcome(ExecutionReason.COMPLETED),
        )
    self.assertEqual((await self.second.get_run("run", "thread"))["status"], "running")
    self.assertEqual(len(await self.second.list_run_events("thread", "run")), 2)

  async def test_same_connection_read_waits_for_commit(self):
    await self.create(self.first, "run")
    entered, release = asyncio.Event(), asyncio.Event()
    original = self.first._insert_fact

    async def insert(*args):
      await original(*args)
      entered.set()
      await release.wait()

    with patch.object(self.first, "_insert_fact", side_effect=insert):
      writer = asyncio.create_task(
        self.first.settle_execution(
          thread_id="thread",
          run_id="run",
          outcome=ExecutionOutcome(ExecutionReason.COMPLETED),
        )
      )
      await asyncio.wait_for(entered.wait(), 2)
      reader = asyncio.create_task(self.first.get_run("run", "thread"))
      await asyncio.sleep(0)
      self.assertFalse(reader.done())
      self.assertEqual(
        (await self.second.get_run("run", "thread"))["status"], "running"
      )
      release.set()
      await writer
      self.assertEqual((await reader)["status"], "completed")


class CompositionTests(unittest.IsolatedAsyncioTestCase):
  async def asyncSetUp(self):
    self.directory = tempfile.TemporaryDirectory()
    self.addCleanup(self.directory.cleanup)
    self.path = Path(self.directory.name) / "runs.db"
    self.config = AppConfig(
      model=ModelConfig(),
      mcp=McpConfig(),
      database=DatabaseConfig(path=str(self.path)),
      checkpointer={"type": "sqlite", "path": str(self.path)},
    )

  async def test_independent_process_blocks_http_imports(self):
    process = await asyncio.create_subprocess_exec(
      sys.executable,
      str(Path(__file__).with_name("runtime_no_http.py")),
      str(self.path),
      stdout=asyncio.subprocess.PIPE,
      stderr=asyncio.subprocess.PIPE,
    )
    try:
      stdout, stderr = await asyncio.wait_for(process.communicate(), 30)
    finally:
      if process.returncode is None:
        process.kill()
        await process.wait()
    self.assertEqual(process.returncode, 0, stderr.decode())
    self.assertIn(b"NO_HTTP_RUNTIME_OK", stdout)

  async def test_real_graph_tool_messages_and_reopened_runtime(self):
    async with open_runtime(self.config, agent_factory=deterministic_agent) as runtime:
      thread_id = await runtime.threads.create_thread()
      execution = await runtime.runs.start_run(thread_id, "1 + 2")
      row = await runtime.runs.wait_run(execution)
      self.assertEqual(row["status"], "completed")
      messages = await runtime.runs.list_run_messages(thread_id, execution.run_id)
      self.assertEqual(
        [m["content"]["type"] for m in messages], ["human", "ai", "tool", "ai"]
      )
      self.assertEqual(messages[2]["content"]["content"], "3")
      self.assertEqual(messages[3]["content"]["content"], "3")
      events = [event async for event in execution.stream.subscribe()]
      self.assertEqual(events[-1].data, {"status": "completed"})
      self.assertTrue(
        any(
          e.event == "durable_event" and e.data["event_type"] == "tool_message"
          for e in events
        )
      )
    async with open_runtime(self.config, agent_factory=deterministic_agent) as runtime:
      self.assertEqual(await runtime.runs.read_run(thread_id, execution.run_id), row)
      self.assertEqual(
        await runtime.runs.list_run_messages(thread_id, execution.run_id), messages
      )

  async def test_pause_commits_checkpoint_and_remains_busy_after_resource_removal(self):
    async def factory(**kwargs):
      kwargs["middlewares"].append(HumanInTheLoopMiddleware(interrupt_on={"add": True}))
      return await deterministic_agent(**kwargs)

    async with open_runtime(self.config, agent_factory=factory) as runtime:
      thread_id = await runtime.threads.create_thread()
      execution = await runtime.runs.start_run(thread_id, "1 + 2")
      row = await runtime.runs.wait_run(execution)
      self.assertEqual(row["status"], "interrupted")
      self.assertIsNone(row["completed_at"])
      self.assertIsNone(runtime.executions.get(thread_id, execution.run_id))
      facts = await runtime.runs.list_run_events(thread_id, execution.run_id)
      pause = facts[-1]["content"]
      self.assertTrue(pause["checkpoint"]["configurable"]["checkpoint_id"])
      self.assertTrue(pause["interrupts"][0]["id"])
      events = [event async for event in execution.stream.subscribe()]
      self.assertEqual(events[-1].data, {"status": "interrupted"})
      self.assertEqual([e.data for e in events if e.event == "durable_event"], facts)
      with self.assertRaises(ThreadBusy):
        await runtime.runs.start_run(thread_id, "another")

  async def test_initialization_failure_closes_store_and_checkpointer(self):
    captured = {}

    async def fail(**kwargs):
      self.assertEqual(kwargs["middlewares"], [])
      captured["checkpointer"] = kwargs["checkpointer"]
      raise ValueError("factory failed")

    original_open = ChatStore.open

    async def capture_store(path):
      store = await original_open(path)
      captured["store"] = store
      return store

    with patch("app.persistence.chat_store.ChatStore.open", side_effect=capture_store):
      with self.assertRaisesRegex(ValueError, "factory failed"):
        async with open_runtime(self.config, agent_factory=fail):
          self.fail("Unexpected runtime")
    with self.assertRaises(ValueError):
      await captured["store"].list_threads()
    with self.assertRaises(ValueError):
      await captured["checkpointer"].conn.execute("SELECT 1")

  async def test_context_exit_reclaims_graph_before_closing_storage(self):
    for caller_fails in (False, True):
      with self.subTest(caller_fails=caller_fails):
        entered, cleaned = asyncio.Event(), asyncio.Event()
        captured = {}

        async def factory(
          captured=captured, entered=entered, cleaned=cleaned, **kwargs
        ):
          checkpointer = kwargs["checkpointer"]
          captured.update(checkpointer=checkpointer)

          class Agent(BlockingAgent):
            async def astream_events(self, *args, **params):
              stream = await super().astream_events(*args, **params)

              class Context:
                async def __aenter__(self):
                  entered.set()
                  return stream

                async def __aexit__(self, *args):
                  await captured["store"].list_threads()
                  await checkpointer.conn.execute("SELECT 1")
                  cleaned.set()

              return Context()

          return Agent()

        try:
          async with open_runtime(self.config, agent_factory=factory) as runtime:
            captured["store"] = runtime.chat_store
            thread_id = await runtime.threads.create_thread()
            execution = await runtime.runs.start_run(thread_id, "hello")
            await asyncio.wait_for(entered.wait(), 2)
            if caller_fails:
              raise ValueError("caller failed")
        except ValueError as error:
          self.assertTrue(caller_fails)
          self.assertEqual(str(error), "caller failed")
        self.assertTrue(cleaned.is_set())
        self.assertTrue(execution.task.done())
        with self.assertRaises(ValueError):
          await captured["store"].list_threads()
        with self.assertRaises(ValueError):
          await captured["checkpointer"].conn.execute("SELECT 1")
