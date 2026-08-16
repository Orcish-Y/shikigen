import asyncio
import unittest

from langchain_core.messages import HumanMessage

from harness.callback_handler import TokenTracker
from harness.loop import run_agent_loop
from harness.run_manager import RunRecord, RunStatus
from harness.runtime_context import AgentRunContext
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


class LateFailingEventStream(EventStream):
  async def __aexit__(self, exc_type, exc_value, traceback):
    raise RuntimeError("late failure")


class Agent:
  def __init__(self):
    self.config = None
    self.context = None

  async def astream_events(self, *_args, **_kwargs):
    self.config = _kwargs.get("config")
    self.context = _kwargs.get("context")
    return EventStream()


class BlockingAgent:
  async def astream_events(self, *_args, **_kwargs):
    return BlockingEventStream()


class FailingAgent:
  async def astream_events(self, *_args, **_kwargs):
    raise ValueError("stream setup failed")


class LateFailingAgent:
  async def astream_events(self, *_args, **_kwargs):
    return LateFailingEventStream()


class RunAgentLoopTests(unittest.IsolatedAsyncioTestCase):
  async def test_attaches_tracker_and_publishes_zero_usage(self):
    stream = Stream()
    agent = Agent()
    tracker = TokenTracker()

    await run_agent_loop(
      agent,
      HumanMessage(content="hello"),
      record=RunRecord(run_id="run-1", thread_id="thread-1", stream=stream),
      token_tracker=tracker,
    )

    self.assertEqual(agent.config["callbacks"], [tracker])
    self.assertEqual(
      agent.context,
      AgentRunContext(thread_id="thread-1", run_id="run-1"),
    )
    events = [event async for event in stream.subscribe()]
    usage_events = [event for event in events if event.event == "usage"]
    self.assertEqual(
      usage_events[0].data,
      {
        "total_input": 0,
        "total_output": 0,
        "total_tokens": 0,
        "calls": 0,
        "by_model": {},
      },
    )

  async def test_publishes_one_complete_event_for_each_tool_call(self):
    stream = Stream()
    record = RunRecord(run_id="run-1", thread_id="thread-1", stream=stream)

    await run_agent_loop(
      Agent(),
      HumanMessage(content="hello"),
      record=record,
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
    self.assertEqual(record.status, RunStatus.COMPLETED)

  async def test_cancels_consumption_when_abort_signal_wins(self):
    stream = Stream()
    abort_event = asyncio.Event()
    abort_event.set()
    record = RunRecord(
      run_id="run-1",
      thread_id="thread-1",
      stream=stream,
      abort_event=abort_event,
    )

    await run_agent_loop(
      BlockingAgent(),
      HumanMessage(content="hello"),
      record=record,
    )

    events = [event async for event in stream.subscribe()]
    status_events = [event for event in events if event.event == "status"]
    self.assertEqual(status_events[-1].data, {"status": "cancelled"})
    self.assertEqual(record.status, RunStatus.CANCELLED)

  async def test_external_task_cancellation_commits_cancelled(self):
    stream = Stream()
    record = RunRecord(run_id="run-1", thread_id="thread-1", stream=stream)
    task = asyncio.create_task(
      run_agent_loop(
        BlockingAgent(),
        HumanMessage(content="hello"),
        record=record,
      )
    )

    while record.status is RunStatus.PENDING:
      await asyncio.sleep(0)
    task.cancel()

    with self.assertRaises(asyncio.CancelledError):
      await task

    events = [event async for event in stream.subscribe()]
    self.assertEqual(record.status, RunStatus.CANCELLED)
    self.assertEqual(events[-1].data, {"status": "cancelled"})

  async def test_preserves_errors_raised_before_consumption_starts(self):
    stream = Stream()
    record = RunRecord(run_id="run-1", thread_id="thread-1", stream=stream)

    with self.assertRaisesRegex(ValueError, "stream setup failed"):
      await run_agent_loop(
        FailingAgent(),
        HumanMessage(content="hello"),
        record=record,
      )

    events = [event async for event in stream.subscribe()]
    error_events = [event for event in events if event.event == "error"]
    self.assertEqual(len(error_events), 1)
    self.assertEqual(events[-1].event, "error")
    self.assertEqual(events[-1].data, {"message": "stream setup failed"})
    self.assertEqual(record.status, RunStatus.ERROR)

  async def test_does_not_commit_completed_before_stream_context_exits(self):
    stream = Stream()
    record = RunRecord(run_id="run-1", thread_id="thread-1", stream=stream)

    with self.assertRaisesRegex(RuntimeError, "late failure"):
      await run_agent_loop(
        LateFailingAgent(),
        HumanMessage(content="hello"),
        record=record,
      )

    events = [event async for event in stream.subscribe()]
    self.assertEqual(record.status, RunStatus.ERROR)
    self.assertEqual([event.event for event in events].count("status"), 0)
    self.assertEqual(events[-1].data, {"message": "late failure"})
