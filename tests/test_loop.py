import unittest

from langchain_core.messages import HumanMessage

from harness.loop import run_agent_loop
from harness.stream import Stream


class AsyncItems:
  def __init__(self, *items):
    self.items = items

  def __aiter__(self):
    async def iterate():
      for item in self.items:
        yield item

    return iterate()


class ToolCall:
  tool_name = "add"
  input = {"a": 1, "b": 2}

  def __init__(self):
    self.output = None

  @property
  def output_deltas(self):
    async def deltas():
      yield "3"
      self.output = 3

    return deltas()


class EventStream:
  def __init__(self):
    self.values = AsyncItems({"messages": [HumanMessage(content="hello")]})
    self.messages = AsyncItems()
    self.tool_calls = AsyncItems(ToolCall())

  async def __aenter__(self):
    return self

  async def __aexit__(self, exc_type, exc_value, traceback):
    return False


class Agent:
  async def astream_events(self, *_args, **_kwargs):
    return EventStream()


class RunAgentLoopTests(unittest.IsolatedAsyncioTestCase):
  async def test_publishes_one_complete_event_for_each_tool_call(self):
    stream = Stream()
    messages = []

    await run_agent_loop(
      Agent(),
      messages,
      run_id="run-1",
      stream=stream,
    )

    events = [event async for event in stream.subscribe()]
    tool_events = [event for event in events if event.event == "tool_call"]

    self.assertEqual(len(tool_events), 1)
    self.assertEqual(
      tool_events[0].data,
      {
        "name": "add",
        "input": {"a": 1, "b": 2},
        "output": 3,
      },
    )
