"""Cancellation across real runtime contexts, while the Python owner stays alive."""

import asyncio
import io
import tempfile
import unittest
from contextlib import ExitStack, asynccontextmanager
from pathlib import Path
from unittest.mock import patch

import aiosqlite
from aiosqlite.context import Result
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from runtime_fixtures import deterministic_agent
from shikigen.app_config import AppConfig
from shikigen.runtime import open_runtime

from app.desktop import bind_listener, serve_backend
from app.desktop_control import ControlChannel
from app.server import create_app


class DesktopLifecycleTests(unittest.IsolatedAsyncioTestCase):
  def setUp(self):
    root = self.enterContext(tempfile.TemporaryDirectory(prefix="desktop lifecycle "))
    self.config = AppConfig.model_validate(
      {
        "model": {},
        "mcp": {},
        "database": {"path": str(Path(root) / "chat.db")},
        "checkpointer": {"type": "sqlite", "path": str(Path(root) / "checkpoint.db")},
      }
    )

  async def test_cancel_at_each_initialization_boundary_unwinds_storage_and_locks(self):
    # External I/O seams: chat schema, checkpoint setup, MCP discovery, Agent
    # construction, and the recovery SELECT. No replacement runtime/lifecycle.
    for phase in ("chat", "checkpoint", "mcp", "agent", "recovery"):
      with self.subTest(phase=phase):
        await self.cancel_during(self.config, phase)
      # The owner process is still alive: a new runtime can reuse both stores.
      # Also verify per phase before continuing to the next cancellation.
      with patch(
        "shikigen.runtime.composition.create_lead_agent", new=deterministic_agent
      ):
        async with open_runtime(self.config) as runtime:
          self.assertEqual(await runtime.threads.list_threads(), [])

  async def cancel_during(self, config, phase):
    with ExitStack() as patches:
      entered = asyncio.Event()
      cancelled = asyncio.Event()

      async def blocked(*args, **kwargs):
        entered.set()
        try:
          await asyncio.Event().wait()
        finally:
          cancelled.set()

      original_execute = aiosqlite.Connection.execute

      def execute(connection, sql, *args, **kwargs):
        if phase == "chat" or (
          phase == "recovery" and "SELECT" in sql.upper() and "runs" in sql.lower()
        ):
          # Preserve aiosqlite's awaitable async-context-manager API.
          return Result(blocked())
        return original_execute(connection, sql, *args, **kwargs)

      patches.enter_context(
        patch("shikigen.runtime.composition.create_lead_agent", new=deterministic_agent)
      )
      if phase in ("chat", "recovery"):
        patches.enter_context(
          patch.object(aiosqlite.Connection, "execute", new=execute)
        )
      elif phase == "checkpoint":
        patches.enter_context(patch.object(AsyncSqliteSaver, "setup", new=blocked))
      else:
        target = "load_mcp_tools" if phase == "mcp" else "create_lead_agent"
        patches.enter_context(
          patch("shikigen.runtime.composition." + target, new=blocked)
        )
      control = ControlChannel(io.BytesIO(), io.BytesIO(), "initializing")
      with bind_listener(48000) as listener:
        task = asyncio.create_task(serve_backend(config, listener, control))
        try:
          await asyncio.wait_for(entered.wait(), 5)
          control.stopping.set()
          await asyncio.wait_for(task, 3)
          self.assertTrue(cancelled.is_set())
        finally:
          if not task.done():
            task.cancel()
          await asyncio.gather(task, return_exceptions=True)

  async def test_shutdown_keeps_storage_alive_until_http_shutdown_finishes(self):
    for reason in ("control", "caller"):
      with self.subTest(reason=reason):
        await self.shutdown_with_delayed_http(reason)

  async def shutdown_with_delayed_http(self, reason):
    started = asyncio.Event()
    draining = asyncio.Event()
    release = asyncio.Event()
    storage_reads = []

    def delayed_app(*, runtime):
      app = create_app(runtime=runtime)
      original_lifespan = app.router.lifespan_context

      @asynccontextmanager
      async def lifespan(app):
        async with original_lifespan(app) as state:
          started.set()
          try:
            yield state
          finally:
            draining.set()
            await release.wait()
            storage_reads.append(await runtime.threads.list_threads())

      app.router.lifespan_context = lifespan
      return app

    control = ControlChannel(io.BytesIO(), io.BytesIO(), "draining")
    with (
      patch("shikigen.runtime.composition.create_lead_agent", new=deterministic_agent),
      patch("app.server.create_app", new=delayed_app),
      bind_listener(48000) as listener,
    ):
      task = asyncio.create_task(serve_backend(self.config, listener, control))
      try:
        await asyncio.wait_for(started.wait(), 5)
        if reason == "control":
          control.stopping.set()
        else:
          task.cancel()
        await asyncio.wait_for(draining.wait(), 5)
        self.assertFalse(task.done())
        release.set()
        if reason == "caller":
          with self.assertRaises(asyncio.CancelledError):
            await asyncio.wait_for(task, 5)
        else:
          await asyncio.wait_for(task, 5)
        self.assertEqual(storage_reads, [[]])
      finally:
        release.set()
        if not task.done():
          task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    with patch(
      "shikigen.runtime.composition.create_lead_agent", new=deterministic_agent
    ):
      async with open_runtime(self.config) as runtime:
        self.assertEqual(await runtime.threads.list_threads(), [])

  async def test_server_failure_propagates_and_releases_data(self):
    control = ControlChannel(io.BytesIO(), io.BytesIO(), "failed")
    with (
      patch("shikigen.runtime.composition.create_lead_agent", new=deterministic_agent),
      patch("uvicorn.Server.serve", side_effect=RuntimeError("server failed")),
      bind_listener(48000) as listener,
    ):
      with self.assertRaisesRegex(RuntimeError, "server failed"):
        await asyncio.wait_for(serve_backend(self.config, listener, control), 5)

    with patch(
      "shikigen.runtime.composition.create_lead_agent", new=deterministic_agent
    ):
      async with open_runtime(self.config) as runtime:
        self.assertEqual(await runtime.threads.list_threads(), [])
