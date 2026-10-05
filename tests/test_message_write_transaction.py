"""普通消息和运行结算复用事务；消息校验、回滚与广播顺序保持一致。"""

import asyncio
import inspect
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from langchain_core.messages import HumanMessage
from shikigen.app_config import AppConfig, McpConfig, ModelConfig
from shikigen.contracts.runs import MessageConflict
from shikigen.core.execution import ExecutionOutcome, ExecutionReason
from shikigen.persistence import ChatStore
from shikigen.runtime.composition import assemble_runtime
from shikigen.runtime.runs import RunTransitions
from test_failure_partial_message import FailureGraph


class MessageWriteTransactionTests(unittest.IsolatedAsyncioTestCase):
  async def asyncSetUp(self):
    directory = tempfile.TemporaryDirectory()
    self.addCleanup(directory.cleanup)
    self.store = await ChatStore.open(Path(directory.name) / "chat.db")
    self.addAsyncCleanup(self.store.close)
    self.transitions = RunTransitions(self.store)
    await self.store.create_thread("thread")
    await self.transitions.create_run(
      thread_id="thread",
      run_id="run",
      entry_message=HumanMessage(id="entry", content="hi"),
    )
    self.message = {
      "type": "ai",
      "message_id": "answer",
      "content": "  正文\n",
      "tool_calls": [],
      "generation_status": "error",
    }

  async def test_message_and_failure_rollback_with_the_callers_transaction(self):
    before = await self.store.list_run_events("thread", "run")
    with self.assertRaisesRegex(OSError, "rollback after both writes"):
      async with self.store.transaction() as transaction:
        await transaction.events.write_message_in_transaction(
          thread_id="thread", run_id="run", message=self.message
        )
        settlement = await self.transitions.settle_execution_in_transaction(
          transaction,
          thread_id="thread",
          run_id="run",
          outcome=ExecutionOutcome(ExecutionReason.FAILED, error=RuntimeError("cause")),
        )
        self.assertEqual(settlement.status, "error")
        raise OSError("rollback after both writes")
    self.assertEqual(await self.store.list_run_events("thread", "run"), before)
    run_snapshot = await self.store.get_run("run", "thread")
    assert run_snapshot is not None
    self.assertEqual(run_snapshot["status"], "running")

  async def test_message_and_cancellation_rollback_with_the_callers_transaction(self):
    before = await self.store.list_run_events("thread", "run")
    with self.assertRaisesRegex(OSError, "rollback cancellation"):
      async with self.store.transaction() as transaction:
        await transaction.events.write_message_in_transaction(
          thread_id="thread",
          run_id="run",
          message={**self.message, "generation_status": "cancelled"},
        )
        await self.transitions.cancel_run_in_transaction(
          transaction, thread_id="thread", run_id="run"
        )
        raise OSError("rollback cancellation")
    self.assertEqual(await self.store.list_run_events("thread", "run"), before)
    run_snapshot = await self.store.get_run("run", "thread")
    assert run_snapshot is not None
    self.assertEqual(run_snapshot["status"], "running")

  async def test_transactional_and_automatic_writes_share_identity_and_conflicts(self):
    seq = await self.store.reserve_message_sequence(
      thread_id="thread", run_id="run", message_id="answer"
    )
    async with self.store.transaction() as transaction:
      write_result = await transaction.events.write_message_in_transaction(
        thread_id="thread", run_id="run", message=self.message, metadata={"origin": 1}
      )
      self.assertTrue(write_result.inserted)
      self.assertEqual(write_result.event["seq"], seq)
    duplicate = await self.store.append_message(
      thread_id="thread", run_id="run", content=self.message, metadata={"origin": 1}
    )
    self.assertFalse(duplicate.inserted)
    self.assertEqual(duplicate.event, write_result.event)
    with self.assertRaises(MessageConflict):
      await self.store.append_message(
        thread_id="thread", run_id="run", content={**self.message, "content": "改写"}
      )
    with self.assertRaises(MessageConflict):
      async with self.store.transaction() as transaction:
        await transaction.events.write_message_in_transaction(
          thread_id="thread", run_id="run", message=self.message, metadata={"origin": 2}
        )
    self.assertEqual(
      await self.store.get_message("thread", "ai:answer"), duplicate.event
    )

  async def test_normal_message_write_uses_the_same_transactional_writer(self):
    writer = self.store._events.write_message_in_transaction
    with patch.object(
      self.store._events, "write_message_in_transaction", wraps=writer
    ) as shared_writer:
      write_result = await self.store.append_message(
        thread_id="thread",
        run_id="run",
        content={**self.message, "generation_status": "complete"},
      )
    self.assertTrue(write_result.inserted)
    self.assertEqual(shared_writer.await_count, 1)
    self.assertEqual(write_result.event["content"]["generation_status"], "complete")

  async def test_state_transition_interfaces_have_no_message_payload(self):
    state_parameters = {
      "self",
      "transaction",
      "thread_id",
      "run_id",
      "outcome",
      "error_code",
      "invocation_seq",
      "usage",
    }
    for transition_fn in (
      RunTransitions.settle_execution,
      RunTransitions.settle_execution_in_transaction,
      RunTransitions.cancel_run,
      RunTransitions.cancel_run_in_transaction,
    ):
      self.assertLessEqual(
        set(inspect.signature(transition_fn).parameters), state_parameters
      )


class BufferedMessageTransactionTests(unittest.IsolatedAsyncioTestCase):
  async def asyncSetUp(self):
    directory = tempfile.TemporaryDirectory()
    self.addCleanup(directory.cleanup)
    self.store = await ChatStore.open(Path(directory.name) / "chat.db")
    self.addAsyncCleanup(self.store.close)
    self.graph = FailureGraph()
    self.runtime = assemble_runtime(
      config=AppConfig(model=ModelConfig(), mcp=McpConfig()),
      agent=self.graph,
      chat_store=self.store,
    )
    self.addAsyncCleanup(self.runtime.lifecycle.shutdown)
    self.thread = await self.runtime.threads.create_thread()

  async def start(self):
    self.execution = await self.runtime.runs.start_run(self.thread, "原文")
    self.run_id = self.execution.run_id
    await asyncio.wait_for(self.graph.ready.wait(), 3)

  async def test_failure_uses_the_same_writer_and_publishes_message_before_terminal(
    self,
  ):
    await self.start()
    writer = self.store._events.write_message_in_transaction
    with patch.object(
      self.store._events, "write_message_in_transaction", wraps=writer
    ) as shared_writer:
      self.graph.release.set()
      snapshot = await self.runtime.runs.wait_run(self.execution)
    self.assertEqual(snapshot["status"], "error")
    self.assertEqual(shared_writer.await_count, 2)
    durable_events = [
      frame.data
      async for frame in self.execution.stream.subscribe()
      if frame.event == "durable_event"
    ]
    self.assertEqual(
      [event["event_type"] for event in durable_events[-3:]],
      ["ai_message", "ai_message", "run_error"],
    )
    self.assertEqual(
      [event["id"] for event in durable_events],
      sorted(event["id"] for event in durable_events),
    )

  async def test_failure_message_write_rollback_preserves_all_buffers_for_retry(self):
    await self.start()
    before = await self.store.list_run_events(self.thread, self.run_id)
    writer = self.store._events.write_message_in_transaction
    failure_seen = asyncio.Event()

    async def fail_second_message(**kwargs):
      if kwargs["message"]["message_id"] == "b":
        failure_seen.set()
        raise OSError("failure after first message")
      return await writer(**kwargs)

    with patch.object(
      self.store._events,
      "write_message_in_transaction",
      side_effect=fail_second_message,
    ):
      self.graph.release.set()
      await asyncio.wait_for(failure_seen.wait(), 3)
      self.assertEqual(
        await self.store.list_run_events(self.thread, self.run_id), before
      )
      run_snapshot = await self.store.get_run(self.run_id, self.thread)
      assert run_snapshot is not None
      self.assertEqual(run_snapshot["status"], "running")
    self.assertEqual(
      (await self.runtime.runs.wait_run(self.execution))["status"], "error"
    )
    messages = await self.store.list_messages_by_run(self.thread, self.run_id)
    assert messages is not None
    self.assertEqual(
      [message["content"]["content"] for message in messages],
      ["原文", "  开始\n    后续 ", "\n"],
    )
    self.assertEqual(self.graph.calls, 1)
