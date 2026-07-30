import asyncio
import unittest

from harness.stream import Stream


class StreamTests(unittest.IsolatedAsyncioTestCase):
  async def test_broadcasts_each_event_to_every_subscriber(self):
    stream = Stream()

    async def collect_events():
      return [event async for event in stream.subscribe()]

    first_subscriber = asyncio.create_task(collect_events())
    second_subscriber = asyncio.create_task(collect_events())
    await asyncio.sleep(0)

    stream.publish("message", {"text": "hello"})
    stream.close()

    first, second = await asyncio.wait_for(
      asyncio.gather(first_subscriber, second_subscriber),
      timeout=0.1,
    )

    self.assertEqual(first, second)
    self.assertEqual([event.data for event in first], [{"text": "hello"}])

  async def test_replays_buffered_events_to_late_subscribers(self):
    stream = Stream()
    stream.publish("message", {"text": "hello"})
    stream.close()

    first = [event async for event in stream.subscribe()]
    second = [event async for event in stream.subscribe()]

    self.assertEqual(first, second)
    self.assertEqual([event.data for event in first], [{"text": "hello"}])
