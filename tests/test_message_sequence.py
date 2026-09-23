"""6A: reservations order previews and committed facts in the same Thread."""

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from langchain_core.messages import AIMessage, HumanMessage
from shikigen.execution import (
  ExecutionOutcome,
  ExecutionReason,
  ExecutionRegistry,
  RunExecution,
)
from shikigen.messages import message_content
from shikigen.persistence import ChatStore
from shikigen.runtime.run_events import RunEventIngestor
from shikigen.runtime.run_state import MessageConflict


class MessageSequenceTests(unittest.IsolatedAsyncioTestCase):
  async def asyncSetUp(self):
    self.temp = tempfile.TemporaryDirectory()
    self.addCleanup(self.temp.cleanup)
    self.path = Path(self.temp.name) / "chat.db"
    self.store = await ChatStore.open(self.path)
    self.addAsyncCleanup(self.store.close)
    await self.store.create_thread("thread")
    await self.store.create_run(
      thread_id="thread",
      run_id="run",
      entry_message=HumanMessage(id="entry", content="hi"),
    )
    self.registry = ExecutionRegistry()
    self.execution = RunExecution("run", "thread")
    self.registry.install(self.execution)
    self.ingestor = RunEventIngestor(self.store, self.registry)

  async def reserve(self, message_id):
    return await self.store.reserve_message_sequence(
      thread_id="thread", run_id="run", message_id=message_id
    )

  async def test_one_reservation_for_many_tokens_and_complete_replaces_preview(self):
    with patch.object(
      self.store, "reserve_message_sequence", wraps=self.store.reserve_message_sequence
    ) as reserve:
      for text in ["draft"] * 20:
        await self.ingestor.ingest_delta(
          {"message_id": "answer", "text": text, "done": False},
          thread_id="thread",
          run_id="run",
        )
      self.assertEqual(reserve.await_count, 1)
    with self.assertLogs("shikigen.runtime.run_events", level="WARNING"):
      seq = await self.ingestor.ingest_message(
        thread_id="thread",
        run_id="run",
        content=message_content(AIMessage(id="answer", content="corrected")),
      )
    self.execution.stream.close()
    events = [event async for event in self.execution.stream.subscribe()]
    self.assertEqual({event.data["seq"] for event in events}, {seq})
    self.assertEqual(events[-1].data["content"]["content"], "corrected")
    with self.assertRaises(MessageConflict):
      await self.ingestor.ingest_delta(
        {"message_id": "answer", "text": "late", "done": False},
        thread_id="thread",
        run_id="run",
      )
    with self.assertRaises(MessageConflict):
      await self.reserve("answer")

  async def test_out_of_order_commit_and_hole_are_not_history_cursor(self):
    early = await self.reserve("early")
    hole = await self.reserve("abandoned")
    later = await self.store.append_message(
      thread_id="thread",
      run_id="run",
      content=message_content(AIMessage(id="later", content="later")),
    )
    self.assertGreater(later.event["seq"], hole)
    before = await self.store.list_run_events("thread", "run")
    self.assertNotIn(early, [e["seq"] for e in before])
    complete = await self.store.append_message(
      thread_id="thread",
      run_id="run",
      content=message_content(AIMessage(id="early", content="early")),
    )
    self.assertEqual(complete.event["seq"], early)
    settled = await self.store.settle_execution(
      thread_id="thread",
      run_id="run",
      outcome=ExecutionOutcome(ExecutionReason.COMPLETED),
    )
    self.assertGreater(settled.events[-1]["seq"], later.event["seq"])
    facts = await self.store.list_run_events("thread", "run")
    self.assertEqual([e["seq"] for e in facts], sorted(e["seq"] for e in facts))
    self.assertNotIn(hole, [e["seq"] for e in facts])

  async def test_two_connections_reserve_once_and_reopen_reuses_identity(self):
    other = await ChatStore.open(self.path)
    try:
      same = await asyncio.gather(
        self.reserve("same"),
        other.reserve_message_sequence(
          thread_id="thread", run_id="run", message_id="same"
        ),
      )
      self.assertEqual(same[0], same[1])
      different = await asyncio.gather(
        self.reserve("a"),
        other.reserve_message_sequence(
          thread_id="thread", run_id="run", message_id="b"
        ),
      )
      self.assertEqual(len(set(different + same)), 3)
    finally:
      await other.close()
    reopened = await ChatStore.open(self.path)
    try:
      result = await reopened.append_message(
        thread_id="thread",
        run_id="run",
        content=message_content(AIMessage(id="same", content="saved")),
      )
      self.assertEqual(result.event["seq"], same[0])
    finally:
      await reopened.close()

  async def test_reservation_cannot_be_taken_by_another_run(self):
    await self.reserve("owned")
    await self.store.settle_execution(
      thread_id="thread",
      run_id="run",
      outcome=ExecutionOutcome(ExecutionReason.COMPLETED),
    )
    await self.store.create_run(
      thread_id="thread",
      run_id="next",
      entry_message=HumanMessage(id="next-entry", content="hi"),
    )
    with self.assertRaises(MessageConflict):
      await self.store.append_message(
        thread_id="thread",
        run_id="next",
        content=message_content(AIMessage(id="owned", content="wrong run")),
      )
