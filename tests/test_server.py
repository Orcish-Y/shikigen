import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException, Request

from harness.persistence import ChatStore
from harness.run_manager import RunManager, RunStatus
from harness.server import get_run_messages, stream_run_events
from harness.stream import StreamManager


class RunMessagesEndpointTests(unittest.IsolatedAsyncioTestCase):
  async def asyncSetUp(self) -> None:
    self.temp_dir = tempfile.TemporaryDirectory()
    self.store = await ChatStore.open(Path(self.temp_dir.name) / "shikigen.db")
    self.app = FastAPI()
    self.app.state.runtime = SimpleNamespace(chat_store=self.store)
    self.request = Request({"type": "http", "app": self.app})

  async def asyncTearDown(self) -> None:
    await self.store.close()
    self.temp_dir.cleanup()

  async def test_returns_only_messages_from_the_requested_run(self) -> None:
    await self.store.create_thread("thread-1")
    await self.store.create_run("run-1", "thread-1")
    await self.store.append_event(
      thread_id="thread-1",
      run_id="run-1",
      event_type="human_message",
      category="message",
      content={"type": "human", "content": "hello"},
    )

    response = await get_run_messages("thread-1", "run-1", self.request)

    data = response["data"]
    assert isinstance(data, list)
    self.assertEqual(data[0]["content"]["content"], "hello")

  async def test_returns_not_found_for_a_run_from_another_thread(self) -> None:
    await self.store.create_thread("thread-1")
    await self.store.create_thread("thread-2")
    await self.store.create_run("run-1", "thread-1")

    with self.assertRaises(HTTPException) as caught:
      await get_run_messages("thread-2", "run-1", self.request)

    self.assertEqual(caught.exception.status_code, 404)


class StreamChatTests(unittest.IsolatedAsyncioTestCase):
  async def test_serializes_complete_events_as_json_lines(self) -> None:
    manager = RunManager(StreamManager())
    record = manager.create("thread-1")
    record.stream.publish("metadata", {"run_id": record.run_id})
    record.stream.publish("message", {"text": "你", "done": False})
    record.stream.publish("message", {"text": "", "done": True})
    record.stream.publish(
      "tool_call",
      {"name": "search", "input": {}, "output": {}},
    )
    record.stream.close()

    lines = [line async for line in stream_run_events(record, manager)]
    events = [json.loads(line) for line in lines]

    self.assertEqual(
      events,
      [
        {
          "id": "0",
          "event": "metadata",
          "data": {"run_id": record.run_id},
        },
        {
          "id": "1",
          "event": "message.delta",
          "data": {"delta": "你"},
          "output_index": 0,
        },
        {
          "id": "2",
          "event": "message.completed",
          "data": {},
          "output_index": 0,
        },
        {
          "id": "3",
          "event": "tool_call.completed",
          "data": {"name": "search", "input": {}, "output": {}},
          "output_index": 1,
        },
      ],
    )
    self.assertTrue(all(line.endswith("\n") for line in lines))

  async def test_closing_response_cancels_task_and_removes_run(self) -> None:
    manager = RunManager(StreamManager())
    record = manager.create("thread-1")

    async def wait_for_abort(_agent, _message, *, record, token_tracker) -> None:
      record.start()
      record.stream.publish("metadata", {"run_id": record.run_id})
      await record.abort_event.wait()
      record.finish(RunStatus.CANCELLED)

    task = asyncio.create_task(
      wait_for_abort(object(), object(), record=record, token_tracker=None)
    )
    record.task = task
    iterator = stream_run_events(record, manager)
    await anext(iterator)

    try:
      await iterator.aclose()

      self.assertTrue(record.abort_event.is_set())
      self.assertTrue(record.task.done())
      self.assertIsNone(manager.get(record.run_id))
    finally:
      if record.task is not None and not record.task.done():
        record.task.cancel()
        await asyncio.gather(record.task, return_exceptions=True)
      manager.remove(record.run_id)

  async def test_cancelled_consumer_cancels_task_and_removes_run(self) -> None:
    manager = RunManager(StreamManager())
    record = manager.create("thread-1")
    first_event_received = asyncio.Event()

    async def wait_for_abort() -> None:
      record.start()
      record.stream.publish("metadata", {"run_id": record.run_id})
      await record.abort_event.wait()
      record.finish(RunStatus.CANCELLED)

    async def consume() -> None:
      async for _ in stream_run_events(record, manager):
        first_event_received.set()

    task = asyncio.create_task(wait_for_abort())
    record.task = task
    consumer_task = asyncio.create_task(consume())
    await first_event_received.wait()
    consumer_task.cancel()

    with self.assertRaises(asyncio.CancelledError):
      await consumer_task

    self.assertTrue(record.abort_event.is_set())
    self.assertTrue(task.done())
    self.assertIsNone(manager.get(record.run_id))
