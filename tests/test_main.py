import contextlib
import io
import unittest

from main import print_tool_call


class AsyncToolCall:
  tool_name = "get_current_time"
  input = {}
  output = "2026-07-29"

  @property
  def output_deltas(self):
    async def deltas():
      yield "2026-"
      yield "07-29"

    return deltas()


class PrintToolCallTests(unittest.IsolatedAsyncioTestCase):
  async def test_consumes_async_output_deltas(self) -> None:
    output = io.StringIO()

    with contextlib.redirect_stdout(output):
      await print_tool_call(AsyncToolCall())

    self.assertEqual(
      output.getvalue(),
      "\nTool call: get_current_time({})\n2026-07-29\nTool result: 2026-07-29\n",
    )
