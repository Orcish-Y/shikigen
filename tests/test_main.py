import asyncio
import contextlib
import io
import unittest

from harness.run_manager import RunManager, RunStatus
from harness.stream import StreamManager
from main import consume_agent_events, consume_tool_calls


class ConsumeToolCallsTests(unittest.TestCase):
  def test_prints_complete_tool_call(self) -> None:
    output = io.StringIO()

    with contextlib.redirect_stdout(output):
      consume_tool_calls(
        {
          "name": "get_current_time",
          "input": {},
          "output": "2026-07-29",
        }
      )

    self.assertEqual(
      output.getvalue(),
      "\nTool call: get_current_time({})\n\nTool result: 2026-07-29\n",
    )


class ConsumeAgentEventsTests(unittest.IsolatedAsyncioTestCase):
  async def test_commits_terminal_status_only_after_agent_task_succeeds(self) -> None:
    manager = RunManager(StreamManager())
    record = manager.create(thread_id="thread-1")
    record.status = RunStatus.RUNNING

    async def fail_after_closing_stream() -> None:
      record.stream.publish("status", {"status": "completed"})
      record.stream.close()
      await asyncio.sleep(0)
      raise RuntimeError("late failure")

    agent_task = asyncio.create_task(fail_after_closing_stream())

    with self.assertRaisesRegex(RuntimeError, "late failure"):
      await consume_agent_events(record, agent_task, manager)

    self.assertEqual(record.status, RunStatus.RUNNING)
