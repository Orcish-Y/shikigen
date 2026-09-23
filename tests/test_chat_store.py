import tempfile
import unittest
from pathlib import Path

from langchain_core.messages import HumanMessage
from shikigen.execution import ExecutionOutcome, ExecutionReason
from shikigen.persistence import ChatStore


class ChatStoreTests(unittest.IsolatedAsyncioTestCase):
  async def asyncSetUp(self) -> None:
    self.temp_dir = tempfile.TemporaryDirectory()
    database_path = Path(self.temp_dir.name) / "nested" / "shikigen.db"
    self.store = await ChatStore.open(database_path)

  async def asyncTearDown(self) -> None:
    await self.store.close()
    self.temp_dir.cleanup()

  async def create_run(self, run_id: str, content: str = "hello") -> None:
    await self.store.create_run(
      run_id=run_id,
      thread_id="thread-1",
      entry_message=HumanMessage(id=f"entry-{run_id}", content=content),
    )

  async def test_lists_messages_for_exact_thread_and_run_in_thread_order(self) -> None:
    await self.store.create_thread("thread-1")
    await self.create_run("run-1")

    first_seq = await self.store.append_event(
      thread_id="thread-1",
      run_id="run-1",
      event_type="ai_message",
      category="message",
      event_key="ai:thinking",
      content={
        "type": "ai",
        "content": "thinking",
        "message_id": "thinking",
        "tool_calls": [],
      },
    )
    second_seq = await self.store.append_event(
      thread_id="thread-1",
      run_id="run-1",
      event_type="trace",
      category="trace",
      content={"node": "model"},
    )
    answer_seq = await self.store.append_event(
      thread_id="thread-1",
      run_id="run-1",
      event_type="ai_message",
      category="message",
      event_key="ai:answer",
      content={"type": "ai", "content": "hi", "message_id": "answer", "tool_calls": []},
    )
    await self.store.settle_execution(
      thread_id="thread-1",
      run_id="run-1",
      outcome=ExecutionOutcome(ExecutionReason.COMPLETED),
    )
    await self.create_run("run-2", "another run")
    other_seq = await self.store.append_event(
      thread_id="thread-1",
      run_id="run-2",
      event_type="ai_message",
      category="message",
      event_key="ai:other",
      content={
        "type": "ai",
        "content": "other answer",
        "message_id": "other",
        "tool_calls": [],
      },
    )

    messages = await self.store.list_messages_by_run("thread-1", "run-1")

    # running、入口消息、trace、终态都占用 Thread 序号；消息过滤后允许空洞。
    self.assertEqual((first_seq, second_seq, answer_seq, other_seq), (3, 4, 5, 9))
    assert messages is not None
    self.assertEqual([message["seq"] for message in messages], [2, 3, 5])
    self.assertEqual(
      [message["content"]["content"] for message in messages],
      ["hello", "thinking", "hi"],
    )

  async def test_returns_none_when_run_does_not_belong_to_thread(self) -> None:
    await self.store.create_thread("thread-1")
    await self.store.create_thread("thread-2")
    await self.create_run("run-1")

    messages = await self.store.list_messages_by_run("thread-2", "run-1")

    self.assertIsNone(messages)

  async def test_event_key_makes_message_writes_idempotent(self) -> None:
    await self.store.create_thread("thread-1")
    await self.create_run("run-1")

    first_seq = await self.store.append_event(
      thread_id="thread-1",
      run_id="run-1",
      event_type="human_message",
      category="message",
      event_key="human:entry-run-1",
      content={"type": "human", "content": "hello", "message_id": "entry-run-1"},
    )
    repeated_seq = await self.store.append_event(
      thread_id="thread-1",
      run_id="run-1",
      event_type="human_message",
      category="message",
      event_key="human:entry-run-1",
      content={"type": "human", "content": "hello", "message_id": "entry-run-1"},
    )

    messages = await self.store.list_messages_by_run("thread-1", "run-1")

    self.assertEqual(repeated_seq, first_seq)
    assert messages is not None
    self.assertEqual(len(messages), 1)

  async def test_finishing_run_updates_status_and_thread_order(self) -> None:
    await self.store.create_thread("thread-1")
    await self.create_run("run-1")
    await self.store.settle_execution(
      thread_id="thread-1",
      run_id="run-1",
      outcome=ExecutionOutcome(ExecutionReason.COMPLETED),
    )

    row = await self.store.get_run("run-1", "thread-1")
    assert row is not None
    self.assertEqual(row["status"], "completed")
    self.assertIsNotNone(row["completed_at"])
