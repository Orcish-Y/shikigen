"""公开 JSON / SSE 的同一已提交事件、只读错误和取消后补齐。"""

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import aiosqlite
import httpx
from langchain_core.messages import HumanMessage
from shikigen.app_config import AppConfig, McpConfig, ModelConfig
from shikigen.persistence import ChatStore
from shikigen.runtime.composition import assemble_runtime
from shikigen.runtime.runs import RunTransitions
from sse_fixtures import parse_sse_frames
from test_loop import MessageAgent

from app.server import create_app


class RunEventQueryTests(unittest.IsolatedAsyncioTestCase):
  async def asyncSetUp(self):
    directory = tempfile.TemporaryDirectory()
    self.addCleanup(directory.cleanup)
    self.store = await ChatStore.open(Path(directory.name) / "events.db")
    self.addAsyncCleanup(self.store.close)
    self.runtime = assemble_runtime(
      config=AppConfig(model=ModelConfig(), mcp=McpConfig()),
      agent=MessageAgent(),
      chat_store=self.store,
    )
    self.addAsyncCleanup(self.runtime.lifecycle.shutdown)
    app = create_app(runtime=self.runtime)
    await self.enterAsyncContext(app.router.lifespan_context(app))
    self.client = await self.enterAsyncContext(
      httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
      )
    )

  async def test_json_returns_all_public_events_identical_to_sse_in_sequence_order(
    self,
  ):
    thread = await self.runtime.threads.create_thread()
    execution = await self.runtime.runs.start_run(thread, "原文\nhttps://example.org/a")
    await self.runtime.runs.wait_run(execution)
    path = f"/api/threads/{thread}/runs/{execution.run_id}"
    replay = parse_sse_frames((await self.client.get(path + "/stream")).text)
    response = await self.client.get(path + "/events")
    self.assertEqual(response.status_code, 200)
    self.assertEqual(response.headers.get("cache-control"), "no-store")
    events = response.json()["data"]
    self.assertEqual(events, [f["data"] for f in replay if f["event"] == "event"])
    self.assertEqual([e["seq"] for e in events], sorted(e["seq"] for e in events))
    self.assertEqual(
      [e["category"] for e in events], ["lifecycle", "message", "lifecycle"]
    )
    self.assertEqual(events[1]["payload"]["content"], "原文\nhttps://example.org/a")

  async def test_pause_query_never_reconciles_invalid_checkpoint_and_checks_ownership(
    self,
  ):
    thread = await self.runtime.threads.create_thread()
    await RunTransitions(self.store).create_run(
      thread_id=thread,
      run_id="paused",
      entry_message=HumanMessage(id="h", content="hi"),
    )
    async with self.store.transaction() as transaction:
      await transaction.runs.update_state(
        "paused", thread, status="interrupted", terminal=False
      )
    initial_snapshot = await self.runtime.runs.get_run_snapshot(thread, "paused")
    path = f"/api/threads/{thread}/runs/paused"
    for _ in range(2):
      response = await self.client.get(path + "/events")
      self.assertEqual(response.status_code, 200)
      self.assertEqual([e["seq"] for e in response.json()["data"]], [1, 2])
      self.assertEqual((await self.client.get(path)).json()["data"], initial_snapshot)
    for target in (
      f"/api/threads/{thread}/runs/missing/events",
      "/api/threads/other/runs/paused/events",
    ):
      response = await self.client.get(target)
      self.assertEqual(response.status_code, 404)
      self.assertEqual(response.headers.get("cache-control"), "no-store")

  async def test_query_driver_errors_are_no_store_and_preserve_all_facts(self):
    thread = await self.runtime.threads.create_thread()
    execution = await self.runtime.runs.start_run(thread, "持久结果")
    completed_snapshot = await self.runtime.runs.wait_run(execution)
    path = f"/api/threads/{thread}/runs/{execution.run_id}"
    history = (await self.client.get(path + "/events")).json()
    busy_error = sqlite3.OperationalError("database is locked")
    busy_error.sqlite_errorcode = sqlite3.SQLITE_BUSY
    corrupt_error = sqlite3.DatabaseError("database disk image is malformed")
    corrupt_error.sqlite_errorcode = sqlite3.SQLITE_CORRUPT
    for failure, status in ((busy_error, 503), (corrupt_error, 500)):
      with self.subTest(status=status):
        with patch.object(aiosqlite.Connection, "execute", side_effect=failure):
          response = await self.client.get(path + "/events")
        self.assertEqual(response.status_code, status)
        self.assertEqual(response.headers.get("cache-control"), "no-store")
        if status == 503:
          self.assertEqual(response.headers.get("retry-after"), "1")
        self.assertEqual(
          (await self.client.get(path)).json()["data"], completed_snapshot
        )
        self.assertEqual((await self.client.get(path + "/events")).json(), history)

  async def test_cancel_query_can_supplement_reserved_sequence_hole_without_preview(
    self,
  ):
    thread = await self.runtime.threads.create_thread()
    await RunTransitions(self.store).create_run(
      thread_id=thread, run_id="r", entry_message=HumanMessage(id="h", content="hi")
    )
    await self.store.reserve_message_sequence(
      thread_id=thread, run_id="r", message_id="preview"
    )
    path = f"/api/threads/{thread}/runs/r"
    initial_events = (await self.client.get(path + "/events")).json()["data"]
    self.assertEqual([event["seq"] for event in initial_events], [1, 2])
    cancel_response = await self.client.post(path + "/cancel")
    self.assertEqual(cancel_response.json()["data"]["status"], "cancelled")
    cancel_events = (await self.client.get(path + "/events")).json()["data"]
    self.assertEqual([event["seq"] for event in cancel_events], [1, 2, 4])
    self.assertEqual(cancel_events[:-1], initial_events)
    self.assertEqual(cancel_events[-1]["payload"], {"status": "cancelled"})

  async def test_incompatible_stored_event_is_readonly_diagnostic_not_partial_facts(
    self,
  ):
    thread = await self.runtime.threads.create_thread()
    execution = await self.runtime.runs.start_run(thread, "核对未来事件")
    expected_snapshot = await self.runtime.runs.wait_run(execution)
    # External storage boundary: simulate a future schema row, retaining every field.
    async with self.store.transaction() as transaction:
      await transaction.events.insert_fact(
        thread,
        execution.run_id,
        "run_future",
        "lifecycle",
        "future:record",
        {"status": "future", "extra": {"path": "![原文](x.png)"}},
      )
    expected_history = await self.runtime.runs.list_run_events(thread, execution.run_id)
    path = f"/api/threads/{thread}/runs/{execution.run_id}"
    for _ in range(2):
      response = await self.client.get(path + "/events")
      self.assertEqual(response.status_code, 500)
      self.assertEqual(response.headers.get("cache-control"), "no-store")
      diagnostic = response.json()["detail"]
      self.assertEqual(diagnostic["code"], "invalid_run_event")
      self.assertEqual(diagnostic["raw_event"], expected_history[-1])
      self.assertNotIn("data", response.json())
      self.assertEqual((await self.client.get(path)).json()["data"], expected_snapshot)
      self.assertEqual(
        await self.runtime.runs.list_run_events(thread, execution.run_id),
        expected_history,
      )


if __name__ == "__main__":
  unittest.main()
