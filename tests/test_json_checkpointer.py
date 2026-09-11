import tempfile
import unittest

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import empty_checkpoint
from shikigen.checkpoint.json_checkpointer import JsonCheckpointer


class JsonCheckpointerTests(unittest.IsolatedAsyncioTestCase):
  async def test_round_trips_latest_and_exact_checkpoint(self) -> None:
    with tempfile.TemporaryDirectory() as base_dir:
      checkpointer = JsonCheckpointer(base_dir)
      config: RunnableConfig = {"configurable": {"thread_id": "thread-1"}}

      checkpoint = empty_checkpoint()
      checkpoint["id"] = "001"
      saved_config = await checkpointer.aput(
        config,
        checkpoint,
        {"source": "input"},
        {},
      )

      latest = await checkpointer.aget_tuple(config)
      exact = await checkpointer.aget_tuple(saved_config)

      self.assertIsNotNone(latest)
      self.assertIsNotNone(exact)
      assert latest is not None
      assert exact is not None
      self.assertEqual(latest.checkpoint["id"], "001")
      self.assertEqual(exact.checkpoint["id"], "001")
      self.assertEqual(latest.metadata, {"source": "input"})
