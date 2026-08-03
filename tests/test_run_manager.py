import asyncio
import unittest

from harness.run_manager import RunManager
from harness.stream import StreamManager


class RunManagerTests(unittest.IsolatedAsyncioTestCase):
  async def test_cancel_uses_abort_signal_without_cancelling_task(self) -> None:
    manager = RunManager(StreamManager())
    record = manager.create(thread_id="thread-1")
    task = asyncio.create_task(asyncio.Event().wait())
    record.task = task

    try:
      manager.cancel(record.run_id)
      await asyncio.sleep(0)

      self.assertTrue(record.abort_event.is_set())
      self.assertFalse(task.done())
    finally:
      task.cancel()
      await asyncio.gather(task, return_exceptions=True)
