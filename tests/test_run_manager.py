import asyncio
import unittest

from shikigen.run_manager import RunManager, RunStatus
from shikigen.stream import StreamManager


class RunManagerTests(unittest.IsolatedAsyncioTestCase):
  async def test_finish_commits_status_event_and_closes_stream(self) -> None:
    manager = RunManager(StreamManager())
    record = manager.create(thread_id="thread-1")

    record.start()
    record.finish(RunStatus.COMPLETED)

    events = [event async for event in record.stream.subscribe()]
    self.assertEqual(record.status, RunStatus.COMPLETED)
    self.assertEqual(events[-1].event, "status")
    self.assertEqual(events[-1].data, {"status": "completed"})

  async def test_error_finish_commits_error_event(self) -> None:
    manager = RunManager(StreamManager())
    record = manager.create(thread_id="thread-1")

    record.start()
    record.finish(RunStatus.ERROR, error=ValueError("broken"))

    events = [event async for event in record.stream.subscribe()]
    self.assertEqual(record.status, RunStatus.ERROR)
    self.assertEqual(events[-1].event, "error")
    self.assertEqual(events[-1].data, {"message": "broken"})

  async def test_terminal_status_can_only_be_committed_once(self) -> None:
    manager = RunManager(StreamManager())
    record = manager.create(thread_id="thread-1")
    record.start()
    record.finish(RunStatus.COMPLETED)

    with self.assertRaisesRegex(RuntimeError, "Cannot finish"):
      record.finish(RunStatus.CANCELLED)

  async def test_completed_run_does_not_block_next_run_for_thread(self) -> None:
    manager = RunManager(StreamManager())
    first = manager.create(thread_id="thread-1")
    first.start()
    first.finish(RunStatus.COMPLETED)

    second = manager.create(thread_id="thread-1")

    self.assertNotEqual(first.run_id, second.run_id)

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

  async def test_release_aborts_waits_and_removes_run(self) -> None:
    manager = RunManager(StreamManager())
    record = manager.create(thread_id="thread-1")

    async def wait_for_abort() -> None:
      record.start()
      await record.abort_event.wait()
      record.finish(RunStatus.CANCELLED)

    record.task = asyncio.create_task(wait_for_abort())
    await asyncio.sleep(0)

    await manager.release(record.run_id)

    self.assertTrue(record.abort_event.is_set())
    self.assertTrue(record.task.done())
    self.assertEqual(record.status, RunStatus.CANCELLED)
    self.assertIsNone(manager.get(record.run_id))

  async def test_release_is_idempotent(self) -> None:
    manager = RunManager(StreamManager())
    record = manager.create(thread_id="thread-1")

    await manager.release(record.run_id)
    await manager.release(record.run_id)

    self.assertIsNone(manager.get(record.run_id))

  async def test_shutdown_cancels_tasks_and_removes_all_runs(self) -> None:
    manager = RunManager(StreamManager())
    first = manager.create(thread_id="thread-1")
    second = manager.create(thread_id="thread-2")
    first.task = asyncio.create_task(asyncio.Event().wait())
    second.task = asyncio.create_task(asyncio.Event().wait())

    await manager.shutdown()

    self.assertTrue(first.task.done())
    self.assertTrue(second.task.done())
    self.assertIsNone(manager.get(first.run_id))
    self.assertIsNone(manager.get(second.run_id))
