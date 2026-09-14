import asyncio
import unittest

from shikigen.stream import Stream


class StreamTests(unittest.IsolatedAsyncioTestCase):
  async def test_closes_subscription_before_first_iteration(self):
    stream = Stream()
    subscription = stream.subscribe()
    self.assertEqual(len(stream._subscribers), 1)

    await subscription.aclose()
    await subscription.aclose()

    self.assertEqual(len(stream._subscribers), 0)
    stream.publish("message", {"text": "after close", "done": False})
    with self.assertRaises(StopAsyncIteration):
      await anext(subscription)

  async def test_registers_before_iteration_and_preserves_event_order(self):
    stream = Stream()
    stream.publish("message", {"text": "history", "done": False})
    subscription = stream.subscribe()
    stream.publish("message", {"text": "live", "done": False})
    stream.close()

    events = [event async for event in subscription]

    self.assertEqual([event.data["text"] for event in events], ["history", "live"])
    self.assertEqual(len(stream._subscribers), 0)
    await subscription.aclose()

  async def test_closing_one_observer_keeps_other_observer_active(self):
    stream = Stream()
    first = stream.subscribe()
    second = stream.subscribe()
    stream.publish("message", {"text": "before", "done": False})
    await anext(first)

    await first.aclose()
    await first.aclose()
    self.assertEqual(len(stream._subscribers), 1)
    stream.publish("message", {"text": "after", "done": False})
    stream.close()

    events = [event async for event in second]
    self.assertEqual([event.data["text"] for event in events], ["before", "after"])
    self.assertEqual(len(stream._subscribers), 0)

  async def test_cancellation_while_waiting_releases_subscription(self):
    stream = Stream()
    subscription = stream.subscribe()
    started = asyncio.Event()

    async def consume():
      started.set()
      return await anext(subscription)

    task = asyncio.create_task(consume())
    await started.wait()
    task.cancel()
    with self.assertRaises(asyncio.CancelledError):
      await task

    self.assertEqual(len(stream._subscribers), 0)
    await subscription.aclose()

  async def test_cancellation_while_processing_releases_via_finally(self):
    stream = Stream()
    subscription = stream.subscribe()
    stream.publish("message", {"text": "hello", "done": False})
    processing = asyncio.Event()
    blocked = asyncio.Event()

    async def consume():
      try:
        async for _ in subscription:
          processing.set()
          await blocked.wait()
      finally:
        await subscription.aclose()

    task = asyncio.create_task(consume())
    await processing.wait()
    task.cancel()
    with self.assertRaises(asyncio.CancelledError):
      await task

    self.assertEqual(len(stream._subscribers), 0)

  async def test_stream_close_wakes_waiting_observer(self):
    stream = Stream()
    subscription = stream.subscribe()
    started = asyncio.Event()

    async def consume():
      started.set()
      return [event async for event in subscription]

    task = asyncio.create_task(consume())
    await started.wait()
    stream.close()
    stream.close()

    self.assertEqual(await asyncio.wait_for(task, timeout=1), [])
    self.assertEqual(len(stream._subscribers), 0)

  async def test_broadcasts_each_event_to_every_subscriber(self):
    stream = Stream()

    async def collect_events():
      return [event async for event in stream.subscribe()]

    first_subscriber = asyncio.create_task(collect_events())
    second_subscriber = asyncio.create_task(collect_events())
    await asyncio.sleep(0)

    stream.publish("message", {"text": "hello", "done": False})
    stream.close()

    first, second = await asyncio.wait_for(
      asyncio.gather(first_subscriber, second_subscriber),
      timeout=0.1,
    )

    self.assertEqual(first, second)
    self.assertEqual(
      [event.data for event in first],
      [{"text": "hello", "done": False}],
    )

  async def test_replays_buffered_events_to_late_subscribers(self):
    stream = Stream()
    stream.publish("message", {"text": "hello", "done": False})
    stream.close()

    first = [event async for event in stream.subscribe()]
    second = [event async for event in stream.subscribe()]

    self.assertEqual(first, second)
    self.assertEqual(
      [event.data for event in first],
      [{"text": "hello", "done": False}],
    )

  async def test_keeps_transport_projection_out_of_stream_events(self):
    stream = Stream()
    stream.publish("message", {"text": "你", "done": False})
    stream.publish("message", {"text": "", "done": True})
    stream.close()

    events = [event async for event in stream.subscribe()]

    self.assertEqual([event.event for event in events], ["message", "message"])
    self.assertTrue(all(not hasattr(event, "output_index") for event in events))
