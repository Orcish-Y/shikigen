import tempfile
import unittest

from harness.checkpoint.json_checkpointer import JsonCheckpointer


class JsonCheckpointerTests(unittest.IsolatedAsyncioTestCase):
  async def test_round_trips_latest_and_exact_checkpoint(self) -> None:
    with tempfile.TemporaryDirectory() as base_dir:
      checkpointer = JsonCheckpointer(base_dir)
      config = {"configurable": {"thread_id": "thread-1"}}

      saved_config = await checkpointer.aput(
        config,
        {"id": "001"},
        {"source": "test"},
        {},
      )

      latest = await checkpointer.aget_tuple(config)
      exact = await checkpointer.aget_tuple(saved_config)

      self.assertIsNotNone(latest)
      self.assertIsNotNone(exact)
      self.assertEqual(latest.checkpoint["id"], "001")
      self.assertEqual(exact.checkpoint["id"], "001")
      self.assertEqual(latest.metadata, {"source": "test"})
