import contextlib
import io
import unittest

from main import consume_tool_calls


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
