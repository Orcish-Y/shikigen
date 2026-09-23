import asyncio
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.types import interrupt
from shikigen.app_config import AppConfig, McpConfig, ModelConfig
from shikigen.contracts.runs import RecoveryUnavailable
from shikigen.core.execution import RunExecution
from shikigen.persistence import ChatStore
from shikigen.runtime.composition import assemble_runtime, open_runtime
from shikigen.runtime.runs import RunTransitions


class RecoveryTests(unittest.IsolatedAsyncioTestCase):
  async def asyncSetUp(self):
    directory = tempfile.TemporaryDirectory()
    self.addCleanup(directory.cleanup)
    self.path = Path(directory.name) / "product.db"
    self.store = await ChatStore.open(self.path)
    self.addAsyncCleanup(self.store.close)

    def approve(state):
      interrupt(
        {
          "action_requests": [{"name": "demo", "args": {}, "description": "review"}],
          "review_configs": [{"action_name": "demo", "allowed_decisions": ["approve"]}],
        }
      )
      return {"messages": [AIMessage(id="result", content="done")]}

    graph = StateGraph(MessagesState)
    graph.add_node("approve", approve)
    graph.add_edge(START, "approve")
    graph.add_edge("approve", END)
    self.agent = graph.compile(checkpointer=InMemorySaver())
    self.runtime = assemble_runtime(
      config=AppConfig(model=ModelConfig(), mcp=McpConfig()),
      agent=self.agent,
      chat_store=self.store,
    )
    self.addAsyncCleanup(self.runtime.lifecycle.shutdown)
    self.recovery = self.runtime.runs.recovery

  async def paused(self):
    thread = await self.runtime.threads.create_thread()
    execution = await self.runtime.runs.start_run(thread, "start")
    run = await self.runtime.runs.wait_run(execution)
    self.assertEqual(run["status"], "interrupted")
    return thread, execution.run_id

  async def lost(self):
    thread = await self.runtime.threads.create_thread()
    await RunTransitions(self.store).create_run(
      thread_id=thread,
      run_id=thread,
      entry_message=HumanMessage(id=thread, content="start"),
    )
    return thread, thread

  async def test_lost_idempotency_terminal_and_live_execution(self):
    thread, run_id = await self.lost()
    # 注册本地执行时扫描保持 running。
    execution = RunExecution(thread_id=thread, run_id=run_id)
    self.runtime.executions.install(execution)
    self.assertEqual(
      (await self.recovery.reconcile_run(thread, run_id))["status"], "running"
    )
    self.runtime.executions.remove(execution)
    await self.recovery.reconcile_all()
    first = await self.store.get_run(run_id, thread)
    facts = await self.store.list_run_events(thread, run_id)
    self.assertEqual(first["error_code"], "invocation_lost")
    self.assertTrue(first["usage_pending"])
    self.assertIsNone(first["usage"])
    await self.recovery.reconcile_all()
    self.assertEqual(await self.recovery.reconcile_run(thread, run_id), first)
    self.assertEqual(await self.store.list_run_events(thread, run_id), facts)

  async def test_transient_retry_checks_other_runs_and_can_cancel(self):
    thread, run_id = await self.paused()
    lost_thread, lost_id = await self.lost()
    before = await self.store.list_run_events(thread, run_id)
    with patch.object(self.agent, "aget_state", side_effect=OSError("private detail")):
      with self.assertLogs("shikigen.runtime.recovery", level="WARNING") as logs:
        with self.assertRaises(RecoveryUnavailable) as error:
          await self.runtime.runs.read_run(thread, run_id)
        self.assertNotIn("private detail", str(error.exception))
        task = asyncio.create_task(self.recovery.reconcile_all(retry_delay=30))
        # 捕获重试等待作为同步点，不依赖 sleep 猜测。
        while (await self.store.get_run(lost_id, lost_thread))["status"] == "running":
          await asyncio.sleep(0)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
          await task
      self.assertIn(thread, "\n".join(logs.output))
      self.assertTrue(
        all(
          record.exc_info is not None
          for record in logs.records
          if record.getMessage().startswith("recovery_unavailable ")
        )
      )
    self.assertEqual(await self.store.list_run_events(thread, run_id), before)
    await self.recovery.reconcile_all(retry_delay=0)
    self.assertEqual(
      (await self.runtime.runs.read_run(thread, run_id))["status"], "interrupted"
    )

  async def test_transient_read_then_success_and_scan_retry(self):
    thread, run_id = await self.paused()
    original = self.agent.aget_state
    calls = 0

    async def flaky(*args, **kwargs):
      nonlocal calls
      calls += 1
      if calls == 1:
        raise OSError("temporary")
      return await original(*args, **kwargs)

    with patch.object(self.agent, "aget_state", new=flaky):
      await self.recovery.reconcile_all(retry_delay=0)
    self.assertEqual(calls, 2)
    self.assertEqual(
      (await self.store.get_run(run_id, thread))["status"], "interrupted"
    )
    original_scan = self.store.list_nonterminal_runs
    calls = 0

    async def flaky_scan():
      nonlocal calls
      calls += 1
      if calls == 1:
        error = sqlite3.OperationalError("database is locked")
        error.sqlite_errorcode = sqlite3.SQLITE_BUSY
        raise error
      return await original_scan()

    with patch.object(self.store, "list_nonterminal_runs", new=flaky_scan):
      await self.recovery.reconcile_all(retry_delay=0)
    self.assertEqual(calls, 2)

  async def test_malformed_approval_json_converges_and_scan_continues(self):
    thread, run_id = await self.paused()
    lost_thread, lost_id = await self.lost()
    connection = self.store._connection
    await connection.execute(
      "UPDATE run_events SET content_json = ? "
      "WHERE run_id = ? AND event_type = 'approval_required'",
      ("{", run_id),
    )
    await connection.commit()

    await asyncio.wait_for(self.recovery.reconcile_all(), 5)
    run = await self.runtime.runs.read_run(thread, run_id)
    self.assertEqual(run["status"], "error")
    self.assertEqual(run["error_code"], "approval_state_corrupt")
    self.assertEqual(
      (await self.store.get_run(lost_id, lost_thread))["error_code"], "invocation_lost"
    )
    await self.recovery.reconcile_all()
    cursor = await connection.execute(
      "SELECT content_json FROM run_events WHERE run_id = ? AND event_type = ?",
      (run_id, "run_error"),
    )
    errors = list(await cursor.fetchall())
    self.assertEqual(len(errors), 1)
    self.assertEqual(
      json.loads(errors[0]["content_json"])["error_code"], "approval_state_corrupt"
    )
    # 收敛只追加错误事实，不覆盖损坏的原始数据。
    cursor = await connection.execute(
      "SELECT content_json FROM run_events WHERE run_id = ? AND event_type = ?",
      (run_id, "approval_required"),
    )
    self.assertEqual((await cursor.fetchone())["content_json"], "{")

  async def test_checkpoint_json_decode_error_is_permanent(self):
    thread, run_id = await self.paused()
    with patch.object(
      self.agent, "aget_state", side_effect=json.JSONDecodeError("truncated", "{", 1)
    ):
      await asyncio.wait_for(self.recovery.reconcile_all(), 5)
    self.assertEqual(
      (await self.store.get_run(run_id, thread))["error_code"], "approval_state_corrupt"
    )

  async def test_unexpected_scan_errors_propagate_without_retry(self):
    schema_error = sqlite3.OperationalError("no such table: runs")
    schema_error.sqlite_errorcode = sqlite3.SQLITE_ERROR
    for error in (TypeError("bug"), AttributeError("bug"), schema_error):
      with self.subTest(error=type(error).__name__):
        with (
          patch.object(self.store, "list_nonterminal_runs", side_effect=error) as scan,
          self.assertLogs("shikigen.runtime.recovery", level="ERROR") as logs,
          self.assertRaises(type(error)) as raised,
        ):
          await asyncio.wait_for(self.recovery.reconcile_all(retry_delay=0), 5)
        self.assertIs(raised.exception, error)
        self.assertEqual(scan.await_count, 1)
        self.assertIsNotNone(logs.records[0].exc_info)

  async def test_unexpected_checkpoint_errors_propagate_without_changing_run(self):
    thread, run_id = await self.paused()
    before = await self.store.list_run_events(thread, run_id)
    for error in (TypeError("bug"), AttributeError("bug"), ValueError("bug")):
      with self.subTest(error=type(error).__name__):
        with (
          patch.object(self.agent, "aget_state", side_effect=error) as read,
          self.assertLogs("shikigen.runtime.recovery", level="ERROR") as logs,
          self.assertRaises(type(error)) as raised,
        ):
          await asyncio.wait_for(self.recovery.reconcile_all(retry_delay=0), 5)
        self.assertIs(raised.exception, error)
        self.assertEqual(read.await_count, 1)
        self.assertIsNotNone(logs.records[0].exc_info)
        self.assertIn(run_id, logs.records[0].getMessage())
    self.assertEqual(
      (await self.store.get_run(run_id, thread))["status"], "interrupted"
    )
    self.assertEqual(await self.store.list_run_events(thread, run_id), before)

  async def test_corrupt_read_and_resume_defense(self):
    for access in ("read", "resume"):
      with self.subTest(access=access):
        thread, run_id = await self.paused()
        facts = await self.store.list_run_events(thread, run_id)
        required = next(e for e in facts if e["event_type"] == "approval_required")
        responses = {
          i["id"]: {"decisions": [{"type": "approve"}]}
          for i in required["content"]["interrupts"]
        }
        # 同一 agent 的精确 checkpoint 成功读取但不再有 Interrupt。
        original = self.agent.aget_state

        async def corrupt(*args, original=original, **kwargs):
          state = await original(*args, **kwargs)
          return state._replace(tasks=(), next=(), interrupts=())

        with patch.object(self.agent, "aget_state", new=corrupt):
          if access == "read":
            run = await self.runtime.runs.read_run(thread, run_id)
          else:
            from shikigen.contracts.runs import InvalidRunState

            with self.assertRaises(InvalidRunState):
              await self.runtime.runs.resume_run(thread, run_id, responses)
            run = await self.store.get_run(run_id, thread)
        self.assertEqual(run["error_code"], "approval_state_corrupt")
        self.assertFalse(
          any(
            e["event_type"] == "approval_resolved"
            for e in await self.store.list_run_events(thread, run_id)
          )
        )

  async def test_recovery_write_rollback(self):
    thread, run_id = await self.lost()
    before = await self.store.list_run_events(thread, run_id)
    with patch.object(self.store._runs, "update_state", side_effect=OSError("disk")):
      with self.assertRaises(RecoveryUnavailable):
        await self.recovery.reconcile_run(thread, run_id)
    self.assertEqual((await self.store.get_run(run_id, thread))["status"], "running")
    self.assertEqual(await self.store.list_run_events(thread, run_id), before)
    await self.recovery.reconcile_all()

  async def test_startup_wait_is_cancellable_and_closes_resources(self):
    config = AppConfig(
      model=ModelConfig(),
      mcp=McpConfig(),
      database={"path": str(self.path)},
      checkpointer={"type": "sqlite", "path": str(self.path)},
    )
    entered = asyncio.Event()

    async def unavailable(store):
      entered.set()
      raise OSError("offline")

    async def factory(**kwargs):
      return self.agent

    async def start():
      async with open_runtime(config):
        self.fail("Runtime exposed before recovery completed")

    with (
      patch("shikigen.runtime.composition.create_lead_agent", new=factory),
      patch.object(ChatStore, "list_nonterminal_runs", new=unavailable),
    ):
      task = asyncio.create_task(start())
      await entered.wait()
      task.cancel()
      with self.assertRaises(asyncio.CancelledError):
        await asyncio.wait_for(task, 5)
    # 资源已退出，可以重新正常打开同库。
    with patch("shikigen.runtime.composition.create_lead_agent", new=factory):
      async with open_runtime(config):
        pass


class RecoveryCrashTests(unittest.TestCase):
  def test_process_crash_matrix(self):
    script = Path(__file__).with_name("recovery_process.py")
    for phase in (
      "create_uncommitted",
      "created",
      "paused",
      "approval_uncommitted",
      "accepted",
      "resumed",
      "completed",
      "corrupt",
    ):
      with self.subTest(phase=phase), tempfile.TemporaryDirectory() as directory:
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")

        def invoke(mode, env=env):
          return subprocess.run(
            [sys.executable, str(script), directory, mode],
            env=env,
            capture_output=True,
            text=True,
            timeout=25,
          )

        crash = invoke(phase)
        self.assertEqual(crash.returncode, 73, crash.stderr)
        if phase == "create_uncommitted":
          with sqlite3.connect(Path(directory) / "runtime.db") as connection:
            self.assertEqual(
              connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0], 0
            )
            self.assertEqual(
              connection.execute("SELECT COUNT(*) FROM run_events").fetchone()[0], 0
            )
          continue
        restart = invoke("inspect")
        self.assertEqual(restart.returncode, 0, restart.stderr)
        data = json.loads(restart.stdout)
        run, facts = data["run"], data["facts"]
        expected = (
          "interrupted"
          if phase in ("paused", "approval_uncommitted")
          else "completed"
          if phase == "completed"
          else "error"
        )
        self.assertEqual(run["status"], expected)
        if expected == "error":
          self.assertEqual(
            run["error_code"],
            "approval_state_corrupt" if phase == "corrupt" else "invocation_lost",
          )
        self.assertEqual(sum(e["event_type"] == "human_message" for e in facts), 1)
        self.assertEqual(
          sum(e["event_type"] == "approval_resolved" for e in facts),
          int(phase in ("accepted", "resumed", "completed")),
        )
        effects = Path(directory) / "effects"
        self.assertEqual(
          effects.read_text() if effects.exists() else "",
          "effect\n" if phase in ("resumed", "completed") else "",
        )
        again = invoke("inspect")
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual(json.loads(again.stdout), data)
