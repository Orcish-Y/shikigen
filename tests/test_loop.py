import asyncio
import unittest

from langchain_core.messages import HumanMessage

from harness.loop import run_agent_loop
from harness.run_manager import RunRecord
from harness.stream import Stream


class AsyncItems:
  def __init__(self, *items):
    self.items = items

  def __aiter__(self):
    async def iterate():
      for item in self.items:
        yield item

    return iterate()


class BlockingItems:
  def __aiter__(self):
    async def iterate():
      await asyncio.Event().wait()
      yield None

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


class BlockingEventStream(EventStream):
  def __init__(self):
    self.values = BlockingItems()
    self.messages = BlockingItems()
    self.tool_calls = BlockingItems()


class Agent:
  async def astream_events(self, *_args, **_kwargs):
    return EventStream()


class BlockingAgent:
  async def astream_events(self, *_args, **_kwargs):
    return BlockingEventStream()


class FailingAgent:
  async def astream_events(self, *_args, **_kwargs):
    raise ValueError("stream setup failed")


class RunAgentLoopTests(unittest.IsolatedAsyncioTestCase):
  async def test_publishes_one_complete_event_for_each_tool_call(self):
    stream = Stream()

    await run_agent_loop(
      Agent(),
      HumanMessage(content="hello"),
      record=RunRecord(run_id="run-1", thread_id="thread-1", stream=stream),
    )

    events = [event async for event in stream.subscribe()]
    tool_events = [event for event in events if event.event == "tool_call"]
    status_events = [event for event in events if event.event == "status"]

    self.assertEqual(len(tool_events), 1)
    self.assertEqual(
      tool_events[0].data,
      {
        "name": "add",
        "input": {"a": 1, "b": 2},
        "output": 3,
      },
    )
    self.assertEqual(status_events[-1].data, {"status": "completed"})

  async def test_cancels_consumption_when_abort_signal_wins(self):
    stream = Stream()
    abort_event = asyncio.Event()
    abort_event.set()

    await run_agent_loop(
      BlockingAgent(),
      HumanMessage(content="hello"),
      record=RunRecord(
        run_id="run-1",
        thread_id="thread-1",
        stream=stream,
        abort_event=abort_event,
      ),
    )

    events = [event async for event in stream.subscribe()]
    status_events = [event for event in events if event.event == "status"]
    self.assertEqual(status_events[-1].data, {"status": "cancelled"})

  async def test_preserves_errors_raised_before_consumption_starts(self):
    stream = Stream()

    with self.assertRaisesRegex(ValueError, "stream setup failed"):
      await run_agent_loop(
        FailingAgent(),
        HumanMessage(content="hello"),
        record=RunRecord(run_id="run-1", thread_id="thread-1", stream=stream),
      )

    events = [event async for event in stream.subscribe()]
    self.assertEqual(events[-1].event, "error")
    self.assertEqual(events[-1].data, {"message": "stream setup failed"})
