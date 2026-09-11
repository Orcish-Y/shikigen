import tempfile
import unittest
from pathlib import Path

from app.persistence import ChatStore


class ChatStoreTests(unittest.IsolatedAsyncioTestCase):
  async def asyncSetUp(self) -> None:
    self.temp_dir = tempfile.TemporaryDirectory()
    database_path = Path(self.temp_dir.name) / "nested" / "shikigen.db"
    self.store = await ChatStore.open(database_path)

  async def asyncTearDown(self) -> None:
    await self.store.close()
    self.temp_dir.cleanup()

  async def test_lists_messages_for_exact_thread_and_run_in_thread_order(self) -> None:
    await self.store.create_thread("thread-1")
    await self.store.create_run("run-1", "thread-1")
    await self.store.create_run("run-2", "thread-1")

    first_seq = await self.store.append_event(
      thread_id="thread-1",
      run_id="run-1",
      event_type="human_message",
      category="message",
      content={"type": "human", "content": "hello"},
    )
    second_seq = await self.store.append_event(
      thread_id="thread-1",
      run_id="run-1",
      event_type="trace",
      category="trace",
      content={"node": "model"},
    )
    third_seq = await self.store.append_event(
      thread_id="thread-1",
      run_id="run-2",
      event_type="human_message",
      category="message",
      content={"type": "human", "content": "another run"},
    )
    fourth_seq = await self.store.append_event(
      thread_id="thread-1",
      run_id="run-1",
      event_type="ai_message",
      category="message",
      content={"type": "ai", "content": "hi"},
    )

    messages = await self.store.list_messages_by_run("thread-1", "run-1")

    self.assertEqual((first_seq, second_seq, third_seq, fourth_seq), (1, 2, 3, 4))
    assert messages is not None
    self.assertEqual([message["seq"] for message in messages], [1, 4])
    self.assertEqual(
      [message["content"]["content"] for message in messages],
      ["hello", "hi"],
    )

  async def test_returns_none_when_run_does_not_belong_to_thread(self) -> None:
    await self.store.create_thread("thread-1")
    await self.store.create_thread("thread-2")
    await self.store.create_run("run-1", "thread-1")

    messages = await self.store.list_messages_by_run("thread-2", "run-1")

    self.assertIsNone(messages)

  async def test_event_key_makes_message_writes_idempotent(self) -> None:
    await self.store.create_thread("thread-1")
    await self.store.create_run("run-1", "thread-1")

    first_seq = await self.store.append_event(
      thread_id="thread-1",
      run_id="run-1",
      event_type="human_message",
      category="message",
      event_key="human:message-1",
      content={"type": "human", "content": "hello"},
    )
    repeated_seq = await self.store.append_event(
      thread_id="thread-1",
      run_id="run-1",
      event_type="human_message",
      category="message",
      event_key="human:message-1",
      content={"type": "human", "content": "hello"},
    )

    messages = await self.store.list_messages_by_run("thread-1", "run-1")

    self.assertEqual(repeated_seq, first_seq)
    assert messages is not None
    self.assertEqual(len(messages), 1)

  async def test_finishing_run_updates_status_and_thread_order(self) -> None:
    await self.store.create_thread("thread-1")
    await self.store.create_run("run-1", "thread-1")

    await self.store.start_run("run-1", "thread-1")
    await self.store.finish_run("run-1", "thread-1", "completed")

    row = await self.store.get_run("run-1", "thread-1")
    assert row is not None
    self.assertEqual(row["status"], "completed")
    self.assertIsNotNone(row["completed_at"])
