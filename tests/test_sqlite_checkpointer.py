import tempfile
import unittest
from pathlib import Path

from harness.checkpoint.sqlite_provider import make_sqlite_checkpointer


class SqliteCheckpointerTests(unittest.IsolatedAsyncioTestCase):
  async def test_creates_database_and_reads_an_empty_thread(self) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
      database_path = Path(temp_dir) / "nested" / "deerflow.db"

      async with make_sqlite_checkpointer(database_path) as checkpointer:
        checkpoint = await checkpointer.aget_tuple(
          {"configurable": {"thread_id": "thread-1"}}
        )

      self.assertIsNone(checkpoint)
      self.assertTrue(database_path.is_file())
