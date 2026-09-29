import asyncio
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import aiosqlite
from runtime_fixtures import deterministic_agent
from shikigen.app_config import AppConfig, McpConfig, ModelConfig
from shikigen.runtime import open_runtime


def config_for(chat, checkpoint=None):
  return AppConfig(
    model=ModelConfig(),
    mcp=McpConfig(),
    database={"path": str(chat)},
    checkpointer={"type": "sqlite", "path": str(checkpoint or chat)},
  )


class RuntimeDataTests(unittest.IsolatedAsyncioTestCase):
  async def asyncSetUp(self):
    directory = tempfile.TemporaryDirectory()
    self.addCleanup(directory.cleanup)
    self.root = Path(directory.name)
    factory = patch(
      "shikigen.runtime.composition.create_lead_agent", new=deterministic_agent
    )
    factory.start()
    self.addCleanup(factory.stop)

  async def test_contender_fails_without_disturbing_owner_and_can_retry(self):
    config = config_for(self.root / "chat.db")
    async with open_runtime(config) as owner:
      with self.assertRaisesRegex(RuntimeError, "Runtime data is in use"):
        async with open_runtime(config):
          self.fail("A second runtime acquired the same database")
      thread = await owner.threads.create_thread()
      self.assertTrue(await owner.chat_store.thread_exists(thread))
    async with open_runtime(config) as reopened:
      self.assertTrue(await reopened.chat_store.thread_exists(thread))

  async def test_hardlink_is_rejected_before_any_database_initialization(self):
    target = self.root / "target.db"
    target.touch()
    alias = self.root / "alias.db"
    os.link(target, alias)
    chat = self.root / "unopened.db"
    with self.assertRaisesRegex(ValueError, "Unsupported runtime data path"):
      async with open_runtime(config_for(chat, alias)):
        self.fail("Hardlinked data was accepted")
    self.assertFalse(chat.exists())
    self.assertEqual(target.stat().st_size, 0)

  async def start_worker(self, config):
    process = await asyncio.create_subprocess_exec(
      sys.executable,
      str(Path(__file__).with_name("runtime_data_worker.py")),
      config.model_dump_json(),
      stdin=asyncio.subprocess.PIPE,
      stdout=asyncio.subprocess.PIPE,
      stderr=asyncio.subprocess.PIPE,
    )

    async def cleanup():
      if process.returncode is None:
        process.kill()
      await process.communicate()

    self.addAsyncCleanup(cleanup)
    return process, await self.read_worker(process)

  async def read_worker(self, process):
    line = await asyncio.wait_for(process.stdout.readline(), 30)
    if not line:
      self.fail((await process.stderr.read()).decode())
    return json.loads(line)

  async def command(self, process, command):
    process.stdin.write((command + "\n").encode())
    await process.stdin.drain()
    return await self.read_worker(process)

  async def test_process_partial_overlap_rolls_back_before_database_creation(self):
    a, b, c = (self.root / name for name in ("a.db", "b.db", "c.db"))
    owner, result = await self.start_worker(config_for(c))
    self.assertEqual(result["status"], "ready")
    _, rejected = await self.start_worker(config_for(a, c))
    self.assertEqual(rejected["error"], "RuntimeDataInUse")
    self.assertFalse(a.exists())
    independent, ready = await self.start_worker(config_for(a, b))
    self.assertEqual(ready["status"], "ready")
    _, rejected = await self.start_worker(config_for(c))
    self.assertEqual(rejected["error"], "RuntimeDataInUse")
    self.assertEqual(
      (await self.command(owner, "run"))["results"], ["completed", "completed"]
    )
    self.assertEqual((await self.command(independent, "exit"))["status"], "closed")
    self.assertEqual((await self.command(owner, "exit"))["status"], "closed")
    successor, ready = await self.start_worker(config_for(a, c))
    self.assertEqual(ready["status"], "ready")
    self.assertEqual((await self.command(successor, "exit"))["status"], "closed")

  async def test_process_crash_releases_locks_and_keeps_sidecars(self):
    config = config_for(self.root / "crash.db")
    owner, result = await self.start_worker(config)
    self.assertEqual(result["status"], "ready")
    owner.kill()
    await owner.wait()
    sidecars = list(self.root.glob("*.runtime.lock"))
    self.assertEqual(len(sidecars), 1)
    successor, result = await self.start_worker(config)
    self.assertEqual(result["status"], "ready")
    self.assertEqual((await self.command(successor, "exit"))["status"], "closed")
    self.assertTrue(sidecars[0].exists())

  @unittest.skipUnless(os.name == "nt", "Windows handle inheritance")
  async def test_live_tool_child_does_not_keep_runtime_lock(self):
    import win32api
    import win32con
    import win32event

    config = config_for(self.root / "tool.db")
    owner, result = await self.start_worker(config)
    self.assertEqual(result["status"], "ready")
    spawned = await self.command(owner, "spawn")
    child = win32api.OpenProcess(
      win32con.PROCESS_TERMINATE | win32con.SYNCHRONIZE, False, spawned["pid"]
    )
    try:
      self.assertEqual((await self.command(owner, "exit"))["status"], "closed")
      self.assertEqual(win32event.WaitForSingleObject(child, 0), win32con.WAIT_TIMEOUT)
      successor, result = await self.start_worker(config)
      self.assertEqual(result["status"], "ready")
      self.assertEqual((await self.command(successor, "exit"))["status"], "closed")
    finally:
      win32api.TerminateProcess(child, 0)
      win32event.WaitForSingleObject(child, 5000)
      child.Close()

  async def test_relative_alias_deduplicates_same_database(self):
    path = self.root / "relative.db"
    config = config_for(path, os.path.relpath(path))
    async with open_runtime(config) as runtime:
      await runtime.threads.create_thread()
      with self.assertRaisesRegex(RuntimeError, "Runtime data is in use"):
        async with open_runtime(config_for(os.path.relpath(path))):
          self.fail("Relative path bypassed ownership")
    self.assertEqual(len(list(self.root.glob("*.runtime.lock"))), 1)

  @unittest.skipUnless(os.name == "nt", "Windows path aliases")
  async def test_case_alias_of_new_database_is_deduplicated(self):
    async with open_runtime(config_for(self.root / "Case.db", self.root / "case.db")):
      pass
    self.assertEqual(len(list(self.root.glob("*.runtime.lock"))), 1)

  @unittest.skipUnless(os.name == "nt", "Windows junctions")
  async def test_junction_parent_is_rejected(self):
    target = self.root / "directory"
    target.mkdir()
    alias = self.root / "junction"
    result = subprocess.run(
      ["cmd", "/c", "mklink", "/J", str(alias), str(target)],
      capture_output=True,
    )
    self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
    try:
      with self.assertRaisesRegex(ValueError, "Unsupported runtime data path"):
        async with open_runtime(config_for(alias / "data.db")):
          self.fail("Junction parent accepted")
      self.assertFalse((target / "data.db").exists())
    finally:
      alias.rmdir()

  @unittest.skipUnless(os.name == "nt", "Windows path syntax")
  async def test_network_device_and_ambiguous_paths_are_rejected(self):
    for value in (
      r"\\server\share\data.db",
      r"\\?\C:\data.db",
      "C:relative.db",
      str(self.root / "data.db:stream"),
      str(self.root / "data.db."),
      str(self.root / "NUL"),
    ):
      with self.subTest(value=value):
        with self.assertRaisesRegex(ValueError, "Unsupported runtime data path"):
          async with open_runtime(config_for(value)):
            self.fail("Unsupported path accepted")

  async def test_memory_checkpoint_does_not_lock_its_unused_path(self):
    shared = self.root / "shared.db"
    first = config_for(self.root / "chat.db")
    first.checkpointer.type = "memory"
    first.checkpointer.path = str(shared)
    async with open_runtime(first):
      self.assertFalse(shared.exists())
      async with open_runtime(config_for(shared)):
        pass

  async def test_lock_file_cannot_be_used_as_a_database(self):
    with self.assertRaisesRegex(ValueError, "Unsupported runtime data path"):
      async with open_runtime(config_for(self.root / "data.db.runtime.lock")):
        self.fail("Reserved lock filename accepted as database")

  async def test_initialization_cancellation_releases_ownership(self):
    config = config_for(self.root / "cancel.db")
    entered = asyncio.Event()

    async def blocked_factory(**kwargs):
      entered.set()
      await asyncio.Event().wait()

    async def start():
      async with open_runtime(config):
        self.fail("Initialization should have been cancelled")

    with patch("shikigen.runtime.composition.create_lead_agent", new=blocked_factory):
      task = asyncio.create_task(start())
      await asyncio.wait_for(entered.wait(), 5)
      task.cancel()
      with self.assertRaises(asyncio.CancelledError):
        await task
    async with open_runtime(config) as runtime:
      await runtime.threads.create_thread()

  async def test_locks_remain_until_both_connections_finish_closing(self):
    chat, checkpoint = self.root / "chat.db", self.root / "checkpoint.db"
    config = config_for(chat, checkpoint)
    context = open_runtime(config)
    await context.__aenter__()
    original_close = aiosqlite.Connection.close
    closing = asyncio.Queue()
    release = asyncio.Event()

    async def delayed_close(connection):
      release.clear()
      await closing.put(True)
      await release.wait()
      await original_close(connection)

    with patch.object(aiosqlite.Connection, "close", new=delayed_close):
      task = asyncio.create_task(context.__aexit__(None, None, None))
      try:
        for _ in range(2):
          await asyncio.wait_for(closing.get(), 5)
          for path in (chat, checkpoint):
            _, result = await self.start_worker(config_for(path))
            self.assertEqual(result["error"], "RuntimeDataInUse")
          release.set()
        await asyncio.wait_for(task, 5)
      finally:
        release.set()
        if not task.done():
          task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    successor, result = await self.start_worker(config)
    self.assertEqual(result["status"], "ready")
    self.assertEqual((await self.command(successor, "exit"))["status"], "closed")

  async def test_symlink_data_and_parent_are_rejected(self):
    target = self.root / "target.db"
    target.touch()
    alias = self.root / "symlink.db"
    directory_alias = self.root / "symlink-directory"
    try:
      alias.symlink_to(target)
      directory_alias.symlink_to(self.root, target_is_directory=True)
    except OSError as error:
      if getattr(error, "winerror", None) == 1314:
        self.skipTest("Windows symlink privilege is unavailable")
      raise
    try:
      for path in (alias, directory_alias / "new.db"):
        with self.assertRaisesRegex(ValueError, "Unsupported runtime data path"):
          async with open_runtime(config_for(path)):
            self.fail("Symbolic link accepted")
    finally:
      alias.unlink()
      directory_alias.unlink()

  async def test_hardlinked_sidecar_is_rejected(self):
    path = self.root / "chat.db"
    sidecar = self.root / "chat.db.runtime.lock"
    sidecar.touch()
    os.link(sidecar, self.root / "lock-alias")
    with self.assertRaisesRegex(ValueError, "Unsupported runtime data path"):
      async with open_runtime(config_for(path)):
        self.fail("Hardlinked lock accepted")
    self.assertFalse(path.exists())

  @unittest.skipUnless(os.name == "nt", "Windows short filenames")
  async def test_short_filename_alias_contends_with_long_name(self):
    import win32api

    path = self.root / "a-long-database-filename.db"
    async with open_runtime(config_for(path)):
      alias = win32api.GetShortPathName(str(path))
      if alias == str(path):
        self.skipTest("8.3 filename generation is disabled on this volume")
      with self.assertRaisesRegex(RuntimeError, "Runtime data is in use"):
        async with open_runtime(config_for(alias)):
          self.fail("Short path bypassed ownership")
