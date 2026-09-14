import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from langgraph.checkpoint.base import empty_checkpoint
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from pydantic import ValidationError
from shikigen.app_config import AppConfig, CheckpointerConfig, McpConfig, ModelConfig
from shikigen.checkpoint import make_checkpointer


def config_for(path: str, backend: str = "sqlite") -> AppConfig:
  return AppConfig.model_validate(
    {
      "model": {},
      "mcp": {},
      "checkpointer": {"type": backend, "path": path},
    }
  )


class SqliteCheckpointerTests(unittest.IsolatedAsyncioTestCase):
  async def test_creates_database_and_reads_an_empty_thread(self) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
      database_path = Path(temp_dir) / "nested" / "deerflow.db"

      async with make_checkpointer(config_for(str(database_path))) as checkpointer:
        checkpoint = await checkpointer.aget_tuple(
          {"configurable": {"thread_id": "thread-1"}}
        )

      self.assertIsNone(checkpoint)
      self.assertTrue(database_path.is_file())

  async def test_persists_across_reopen_and_closes_on_exception(self):
    with tempfile.TemporaryDirectory() as temp_dir:
      config = config_for(str(Path(temp_dir) / "checkpoint.db"))
      thread = {"configurable": {"thread_id": "persisted", "checkpoint_ns": ""}}
      async with make_checkpointer(config) as saver:
        checkpoint = empty_checkpoint()
        checkpoint["channel_values"] = {"answer": 42}
        saved = await saver.aput(thread, checkpoint, {}, {})
      assert isinstance(saver, AsyncSqliteSaver)
      with self.assertRaises(ValueError):
        await saver.conn.execute("SELECT 1")
      with self.assertRaisesRegex(RuntimeError, "caller failed"):
        async with make_checkpointer(config) as saver:
          assert isinstance(saver, AsyncSqliteSaver)
          restored = await saver.aget_tuple(saved)
          self.assertIsNotNone(restored)
          self.assertEqual(restored.checkpoint["channel_values"], {"answer": 42})
          raise RuntimeError("caller failed")
      with self.assertRaises(ValueError):
        await saver.conn.execute("SELECT 1")

  async def test_setup_failure_closes_connection(self):
    connections = []

    async def fail_setup(saver):
      connections.append(saver.conn)
      raise RuntimeError("setup failed")

    with tempfile.TemporaryDirectory() as temp_dir:
      with patch.object(AsyncSqliteSaver, "setup", fail_setup):
        with self.assertRaisesRegex(RuntimeError, "setup failed"):
          async with make_checkpointer(config_for(str(Path(temp_dir) / "db"))):
            self.fail("Should not yield on setup failure")
      with self.assertRaises(ValueError):
        await connections[0].execute("SELECT 1")

  async def test_memory_is_independent_and_does_not_create_files(self):
    with tempfile.TemporaryDirectory() as temp_dir:
      path = Path(temp_dir) / "unused" / "db"
      config = config_for(str(path), "memory")
      with patch("shikigen.checkpoint.provider.load_app_config") as load:
        async with make_checkpointer(config) as first:
          async with make_checkpointer(config) as second:
            self.assertIsInstance(first, InMemorySaver)
            self.assertIsNot(first, second)
        load.assert_not_called()
      self.assertFalse(path.parent.exists())

  async def test_omitted_config_uses_loader_once(self):
    config = config_for("unused", "memory")
    with patch(
      "shikigen.checkpoint.provider.load_app_config", return_value=config
    ) as load:
      async with make_checkpointer() as saver:
        self.assertIsInstance(saver, InMemorySaver)
      load.assert_called_once_with()

  def test_config_defaults_and_validation(self):
    config = AppConfig(model=ModelConfig(), mcp=McpConfig())
    self.assertEqual(config.checkpointer.type, "sqlite")
    self.assertEqual(config.checkpointer.path, ".shikigen/data/shikigen.db")
    for invalid in ({"type": "unknown"}, {"path": ""}, {"typo": True}):
      with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
        CheckpointerConfig.model_validate(invalid)
