import asyncio
import unittest

from shikigen.stream import Stream


class StreamTests(unittest.IsolatedAsyncioTestCase):
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
