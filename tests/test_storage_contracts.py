"""4A 的持久事实、数据库约束与失败边界，全部使用临时 SQLite。"""

import asyncio
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from langchain_core.messages import HumanMessage
from shikigen.execution import ExecutionOutcome, ExecutionPause, ExecutionReason

from app.persistence import ChatStore
from app.run_state import (
  InvalidRunState,
  MessageConflict,
  RunNotFound,
  SchemaMigrationRequired,
  StorageConflict,
  ThreadBusy,
)


class StorageContractTests(unittest.IsolatedAsyncioTestCase):
  async def asyncSetUp(self):
    directory = tempfile.TemporaryDirectory()
    self.addCleanup(directory.cleanup)
    self.path = Path(directory.name) / "chat.db"
    self.store = await ChatStore.open(self.path)
    self.addAsyncCleanup(self.store.close)
    self.reader = await ChatStore.open(self.path)
    self.addAsyncCleanup(self.reader.close)
    await self.store.create_thread("thread")
    self.created = await self.store.create_run(
      thread_id="thread",
      run_id="run",
      entry_message=HumanMessage(id="entry", content="hello"),
    )

  def message(self, **changes):
    return {
      "type": "ai",
      "message_id": "answer",
      "content": "hello",
      "tool_calls": [],
      **changes,
    }

  async def append(self, **changes):
    return await self.store.append_message(
      thread_id="thread",
      run_id="run",
      content=self.message(**changes),
    )

  async def test_creation_and_settlement_return_readable_committed_facts(self):
    self.assertEqual(self.created.run, await self.reader.get_run("run", "thread"))
    self.assertEqual(
      list(self.created.events), await self.reader.list_run_events("thread", "run")
    )
    settled = await self.store.settle_execution(
      thread_id="thread",
      run_id="run",
      outcome=ExecutionOutcome(ExecutionReason.FAILED, error=ValueError("detail")),
      error_code="model_failed",
    )
    self.assertTrue(settled.changed)
    self.assertEqual(settled.error_code, "model_failed")
    row = await self.reader.get_run("run", "thread")
    self.assertEqual(row["error_code"], "model_failed")
    self.assertEqual(
      settled.events[0], (await self.reader.list_run_events("thread", "run"))[-1]
    )
    repeated = await self.reader.settle_execution(
      thread_id="thread",
      run_id="run",
      outcome=ExecutionOutcome(ExecutionReason.COMPLETED),
    )
    self.assertFalse(repeated.changed)
    self.assertEqual(repeated, settled)

  async def test_reordered_payload_is_idempotent_and_conflicts_are_unchanged(self):
    original = await self.append()
    self.assertTrue(original.inserted)
    repeated = await self.reader.append_message(
      thread_id="thread",
      run_id="run",
      content=dict(reversed(list(self.message().items()))),
    )
    self.assertFalse(repeated.inserted)
    self.assertEqual(repeated.event, original.event)
    for changes in ({"content": "different"}, {"tool_calls": [{"id": "call"}]}):
      with self.subTest(changes=changes), self.assertRaises(MessageConflict):
        await self.append(**changes)
    with self.assertRaises(MessageConflict):
      await self.store.append_message(
        thread_id="thread",
        run_id="run",
        content=self.message(),
        metadata={"origin": "different"},
      )
    self.assertEqual(len(await self.reader.list_run_events("thread", "run")), 3)

  async def test_legacy_journal_cannot_bypass_identity_or_conflict_checks(self):
    original = await self.append()
    params = dict(
      thread_id="thread",
      run_id="run",
      category="message",
      event_type="ai_message",
      event_key="ai:answer",
    )
    seq = await self.store.append_event(**params, content=self.message())
    self.assertEqual(seq, original.event["seq"])
    with self.assertRaises(MessageConflict):
      await self.store.append_event(**params, content=self.message(content="changed"))
    with self.assertRaises(ValueError):
      await self.store.append_event(
        **{**params, "event_key": None}, content=self.message()
      )
    with self.assertRaises(ValueError):
      await self.store.append_event(
        **{**params, "category": "trace"}, content=self.message()
      )
    with self.assertRaises(ValueError):
      await self.store.append_event(
        thread_id="thread",
        run_id="run",
        category="lifecycle",
        event_type="run_completed",
        content={"status": "completed"},
      )

  async def test_tool_fallback_and_invalid_messages(self):
    content = {
      "type": "tool",
      "message_id": None,
      "tool_call_id": "call",
      "name": "add",
      "status": "success",
      "content": "3",
    }
    result = await self.store.append_message(
      thread_id="thread",
      run_id="run",
      content=content,
    )
    self.assertEqual(result.event["event_key"], "tool:call")
    for changes in ({"message_id": ""}, {"content": object()}, {"tool_calls": None}):
      with self.subTest(changes=changes), self.assertRaises((ValueError, TypeError)):
        await self.append(**changes)
    with self.assertRaises((ValueError, TypeError)):
      await self.append(content=[{"value": float("nan")}])
    with self.assertRaises(RunNotFound):
      await self.store.append_message(
        thread_id="wrong-thread",
        run_id="run",
        content=self.message(),
      )

  async def test_concurrent_same_message_has_one_new_fact(self):
    first, second = await asyncio.gather(
      self.append(),
      self.reader.append_message(
        thread_id="thread",
        run_id="run",
        content=self.message(),
      ),
    )
    self.assertEqual(first.event, second.event)
    self.assertEqual(sum([first.inserted, second.inserted]), 1)

  async def test_message_commit_failure_and_cancellation_roll_back(self):
    for error in (OSError("commit failed"), asyncio.CancelledError()):
      with self.subTest(error=type(error)):
        with patch.object(self.store._connection, "commit", side_effect=error):
          with self.assertRaises(type(error)):
            await self.append()
        self.assertEqual(len(await self.reader.list_run_events("thread", "run")), 2)
    self.assertEqual((await self.append()).event["seq"], 3)

  async def test_database_rejects_second_nonterminal_even_without_store_api(self):
    # 排他必须覆盖所有非终态，不能只依赖 create_run 的先查后写。
    for current in ("pending", "running", "interrupted"):
      with self.subTest(current=current):
        await self.store._connection.execute("UPDATE runs SET status = ?", (current,))
        await self.store._connection.commit()
        with self.assertRaises(sqlite3.IntegrityError):
          await self.reader._connection.execute(
            """INSERT INTO runs(id, thread_id, status, created_at, updated_at)
            VALUES ('other', 'thread', 'running', 'now', 'now')"""
          )
        await self.reader._connection.rollback()
        with self.assertRaises(ThreadBusy):
          await self.reader.create_run(
            thread_id="thread",
            run_id="other",
            entry_message=HumanMessage(id="other", content="hi"),
          )
    for sql in (
      "UPDATE runs SET status = 'unknown'",
      "UPDATE runs SET status = 'completed'",
    ):
      with self.assertRaises(sqlite3.IntegrityError):
        await self.store._connection.execute(sql)
      await self.store._connection.rollback()

  async def test_identity_conflict_is_application_error_and_rolls_back(self):
    with self.assertRaises(StorageConflict):
      await self.store.create_thread("thread")
    await self.store.create_thread("other")
    with self.assertRaises(StorageConflict) as caught:
      await self.store.create_run(
        thread_id="other",
        run_id="run",
        entry_message=HumanMessage(id="other", content="hi"),
      )
    self.assertNotIsInstance(caught.exception, ThreadBusy)
    self.assertEqual(await self.reader.list_thread_messages("other"), [])

  async def test_pause_replay_returns_original_checkpoint_fact(self):
    first = await self.store.settle_execution(
      thread_id="thread",
      run_id="run",
      outcome=ExecutionOutcome(
        ExecutionReason.INTERRUPTED,
        pause=ExecutionPause(
          checkpoint={"id": "checkpoint"}, interrupts=({"id": "approval"},)
        ),
      ),
    )
    second = await self.reader.settle_execution(
      thread_id="thread",
      run_id="run",
      outcome=ExecutionOutcome(ExecutionReason.COMPLETED),
    )
    self.assertEqual(first.events, second.events)
    self.assertEqual(second.events[0]["content"]["checkpoint"], {"id": "checkpoint"})
    self.assertIsNone((await self.reader.get_run("run", "thread"))["completed_at"])

  async def test_pending_cannot_be_settled_as_success(self):
    await self.store._connection.execute("UPDATE runs SET status = 'pending'")
    await self.store._connection.commit()
    with self.assertRaises(InvalidRunState):
      await self.store.settle_execution(
        thread_id="thread",
        run_id="run",
        outcome=ExecutionOutcome(ExecutionReason.COMPLETED),
      )

  async def test_settlement_cancellation_rolls_back_and_can_retry(self):
    with patch.object(
      self.store._connection, "commit", side_effect=asyncio.CancelledError()
    ):
      with self.assertRaises(asyncio.CancelledError):
        await self.store.settle_execution(
          thread_id="thread",
          run_id="run",
          outcome=ExecutionOutcome(ExecutionReason.COMPLETED),
        )
    self.assertEqual((await self.reader.get_run("run", "thread"))["status"], "running")
    self.assertEqual(len(await self.reader.list_run_events("thread", "run")), 2)
    settled = await self.store.settle_execution(
      thread_id="thread",
      run_id="run",
      outcome=ExecutionOutcome(ExecutionReason.COMPLETED),
    )
    self.assertEqual(settled.events[0]["seq"], 3)


class LegacySchemaTests(unittest.IsolatedAsyncioTestCase):
  async def test_legacy_database_is_rejected_without_schema_or_data_rewrite(self):
    with tempfile.TemporaryDirectory() as directory:
      path = Path(directory) / "legacy.db"
      with sqlite3.connect(path) as connection:
        connection.executescript(
          "CREATE TABLE threads(id TEXT PRIMARY KEY, title TEXT);"
          "INSERT INTO threads VALUES ('old', 'keep me');"
        )
      before = path.read_bytes()
      with self.assertRaises(SchemaMigrationRequired):
        await ChatStore.open(path)
      self.assertEqual(path.read_bytes(), before)
