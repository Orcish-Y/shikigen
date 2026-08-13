import asyncio
import unittest

from harness.run_manager import RunManager, RunStatus
from harness.server import stream_run_events
from harness.stream import StreamManager


class StreamChatTests(unittest.IsolatedAsyncioTestCase):
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
