"""Public conversation-list pagination and committed-run summaries."""

import asyncio
import base64
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import aiosqlite
import httpx
from langchain_core.messages import HumanMessage
from shikigen.app_config import AppConfig, McpConfig, ModelConfig
from shikigen.contracts.runs import RunStatus
from shikigen.core.execution import ExecutionOutcome, ExecutionPause, ExecutionReason
from shikigen.persistence import ChatStore
from shikigen.runtime.composition import assemble_runtime
from shikigen.runtime.runs import RunTransitions

from app.server import create_app

_FIXED_TIME = "2026-09-01T12:00:00+00:00"


def _encoded_cursor(value: object) -> str:
  raw = json.dumps(value, separators=(",", ":")).encode()
  return base64.urlsafe_b64encode(raw).decode().rstrip("=")


class _BlockedDeltaStream:
  async def __aenter__(self):
    return self

  async def __aexit__(self, *_args):
    return False

  def __aiter__(self):
    async def events():
      yield {
        "method": "messages",
        "params": {
          "namespace": [],
          "data": [{"event": "message-start", "role": "ai", "id": "preview"}, {}],
        },
      }
      yield {
        "method": "messages",
        "params": {
          "namespace": [],
          "data": [
            {
              "event": "content-block-delta",
              "delta": {"type": "text-delta", "text": "preview"},
            },
            {},
          ],
        },
      }
      await asyncio.Event().wait()

    return events()


class _BlockedDeltaAgent:
  async def astream_events(self, *_args, **_kwargs):
    return _BlockedDeltaStream()


class ThreadPaginationTests(unittest.IsolatedAsyncioTestCase):
  async def asyncSetUp(self):
    self.directory = tempfile.TemporaryDirectory()
    self.addCleanup(self.directory.cleanup)
    self.path = Path(self.directory.name) / "threads.db"
    self.store = await ChatStore.open(self.path)
    self.addAsyncCleanup(self.store.close)
    self.runtime = assemble_runtime(
      config=AppConfig(model=ModelConfig(), mcp=McpConfig()),
      agent=object(),
      chat_store=self.store,
    )
    self.addAsyncCleanup(self.runtime.lifecycle.shutdown)
    self.app = create_app(runtime=self.runtime)
    await self.enterAsyncContext(self.app.router.lifespan_context(self.app))
    self.client = await self.enterAsyncContext(
      httpx.AsyncClient(
        transport=httpx.ASGITransport(app=self.app, raise_app_exceptions=False),
        base_url="http://test",
      )
    )

  async def _seed_equal_time_threads(self, count: int) -> list[str]:
    ids = [f"thread-{index:03}" for index in range(count)]
    connection = await aiosqlite.connect(self.path)
    try:
      await connection.execute("DELETE FROM threads")
      await connection.executemany(
        "INSERT INTO threads(id, user_id, title, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?)",
        [
          (thread_id, f"user-{index}", f"会话 {index}", _FIXED_TIME, _FIXED_TIME)
          for index, thread_id in enumerate(ids)
        ],
      )
      await connection.commit()
    finally:
      await connection.close()
    return ids

  async def _set_thread_updated_at(self, thread_id: str, timestamp: str) -> None:
    connection = await aiosqlite.connect(self.path)
    try:
      await connection.execute(
        "UPDATE threads SET updated_at = ? WHERE id = ?", (timestamp, thread_id)
      )
      await connection.commit()
    finally:
      await connection.close()

  async def test_client_limit_controls_page_size_and_can_change_between_pages(self):
    ids = await self._seed_equal_time_threads(51)
    first = await self.client.get("/api/threads", params={"limit": 3})
    self.assertEqual(first.status_code, 200)
    self.assertEqual(
      [row["id"] for row in first.json()["data"]], list(reversed(ids))[:3]
    )
    second = await self.client.get(
      "/api/threads",
      params={"limit": 25, "cursor": first.json()["next_cursor"]},
    )
    self.assertEqual(second.status_code, 200)
    self.assertEqual(
      [row["id"] for row in second.json()["data"]], list(reversed(ids))[3:28]
    )
    third = await self.client.get(
      "/api/threads",
      params={"limit": 50, "cursor": second.json()["next_cursor"]},
    )
    self.assertEqual(third.status_code, 200)
    self.assertEqual(
      [row["id"] for row in third.json()["data"]], list(reversed(ids))[28:]
    )
    self.assertIsNone(third.json()["next_cursor"])

  async def test_large_positive_limits_do_not_overflow_sqlite_lookahead(self):
    ids = await self._seed_equal_time_threads(3)
    for limit in (2**63 - 1, 2**63, 10**100):
      with self.subTest(limit=limit):
        response = await self.client.get("/api/threads", params={"limit": str(limit)})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("cache-control"), "no-store")
        self.assertEqual(
          [row["id"] for row in response.json()["data"]], list(reversed(ids))
        )
        self.assertIsNone(response.json()["next_cursor"])
        stored = await self.store.list_threads(limit=limit)
        self.assertEqual(stored, response.json())

  async def test_pages_cover_empty_and_exact_page_boundaries_with_tied_timestamps(self):
    cases = [(20, count) for count in (0, 20, 21, 40, 41)] + [
      (limit, count)
      for limit in (1, 7, 25)
      for count in (0, limit, limit + 1, 2 * limit, 2 * limit + 1)
    ]
    for limit, count in cases:
      with self.subTest(limit=limit, count=count):
        ids = await self._seed_equal_time_threads(count)
        pages = []
        cursor = None
        while True:
          response = await self.client.get(
            "/api/threads",
            params={"limit": limit, **({} if cursor is None else {"cursor": cursor})},
          )
          self.assertEqual(response.status_code, 200)
          self.assertEqual(response.headers.get("cache-control"), "no-store")
          page = response.json()
          self.assertEqual(set(page), {"data", "next_cursor"})
          self.assertLessEqual(len(page["data"]), limit)
          for row in page["data"]:
            self.assertEqual(
              set(row),
              {
                "id",
                "user_id",
                "title",
                "created_at",
                "updated_at",
                "run_id",
                "run_status",
              },
            )
            self.assertIsNone(row["run_id"])
            self.assertIsNone(row["run_status"])
            self.assertEqual(row["created_at"], _FIXED_TIME)
            self.assertEqual(row["updated_at"], _FIXED_TIME)
          pages.append(page["data"])
          cursor = page["next_cursor"]
          if cursor is None:
            break
          self.assertIsInstance(cursor, str)
          self.assertTrue(cursor)

        expected_lengths = (
          [0]
          if count == 0
          else [limit] * (count // limit) + ([count % limit] if count % limit else [])
        )
        self.assertEqual([len(page) for page in pages], expected_lengths)
        listed_ids = [row["id"] for page in pages for row in page]
        self.assertEqual(listed_ids, sorted(ids, reverse=True))
        if count:
          first = pages[0][0]
          index = int(first["id"].removeprefix("thread-"))
          self.assertEqual(
            (first["user_id"], first["title"]), (f"user-{index}", f"会话 {index}")
          )

  async def test_cursor_freezes_deleted_or_moved_boundary_and_can_repeat_moved_rows(
    self,
  ):
    ids = await self._seed_equal_time_threads(41)
    first = (await self.client.get("/api/threads", params={"limit": 20})).json()
    cursor = first["next_cursor"]
    self.assertEqual([row["id"] for row in first["data"]], list(reversed(ids))[:20])

    # Moving the boundary keeps continuation on the original key.
    boundary_id = first["data"][-1]["id"]
    await self._set_thread_updated_at(boundary_id, "2026-09-02T12:00:00+00:00")
    moved_boundary_page = await self.client.get(
      "/api/threads", params={"limit": 20, "cursor": cursor}
    )
    self.assertEqual(
      [row["id"] for row in moved_boundary_page.json()["data"]],
      list(reversed(ids))[20:40],
    )

    # A cursor remains usable after its boundary row is deleted.
    ids = await self._seed_equal_time_threads(41)
    first = (await self.client.get("/api/threads", params={"limit": 20})).json()
    cursor = first["next_cursor"]
    boundary_id = first["data"][-1]["id"]
    connection = await aiosqlite.connect(self.path)
    try:
      await connection.execute("DELETE FROM threads WHERE id = ?", (boundary_id,))
      await connection.commit()
    finally:
      await connection.close()
    second = await self.client.get(
      "/api/threads", params={"limit": 20, "cursor": cursor}
    )
    self.assertEqual(
      [row["id"] for row in second.json()["data"]], list(reversed(ids))[20:40]
    )
    third = await self.client.get(
      "/api/threads", params={"limit": 20, "cursor": second.json()["next_cursor"]}
    )
    self.assertEqual([row["id"] for row in third.json()["data"]], [ids[0]])

    # Moved rows can repeat across pages; clients dedupe them by ID.
    ids = await self._seed_equal_time_threads(41)
    first = (await self.client.get("/api/threads", params={"limit": 20})).json()
    moved_id = first["data"][0]["id"]
    await self._set_thread_updated_at(moved_id, "2026-08-31T12:00:00+00:00")
    second = await self.client.get(
      "/api/threads", params={"limit": 20, "cursor": first["next_cursor"]}
    )
    third = await self.client.get(
      "/api/threads", params={"limit": 20, "cursor": second.json()["next_cursor"]}
    )
    self.assertIn(moved_id, [row["id"] for row in third.json()["data"]])

  async def test_invalid_cursor_shapes_types_and_extra_parameters_are_422(self):
    invalid_cursors = (
      "not-base64!",
      _encoded_cursor([2, _FIXED_TIME, "thread"]),
      _encoded_cursor([True, _FIXED_TIME, "thread"]),
      _encoded_cursor([1, "2026-09-01T12:00:00", "thread"]),
      _encoded_cursor([1, "not-a-time", "thread"]),
      _encoded_cursor([1, _FIXED_TIME, 12]),
      _encoded_cursor([1, _FIXED_TIME, ""]),
      _encoded_cursor({"version": 1, "updated_at": _FIXED_TIME, "id": "thread"}),
    )
    for cursor in invalid_cursors:
      with self.subTest(cursor=cursor):
        response = await self.client.get(
          "/api/threads", params={"limit": 20, "cursor": cursor}
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.headers.get("cache-control"), "no-store")
    for url in (
      "/api/threads?limit=20&other=1",
      "/api/threads?limit=20&cursor=first&cursor=second",
      "/api/threads?limit=3&limit=20",
    ):
      with self.subTest(url=url):
        response = await self.client.get(url)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.headers.get("cache-control"), "no-store")

  async def test_limit_is_required_and_invalid_values_are_uncached_422(self):
    for params in ({}, *({"limit": value} for value in (0, -1, "", "bad", "1.5"))):
      with self.subTest(params=params):
        response = await self.client.get("/api/threads", params=params)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.headers.get("cache-control"), "no-store")
    parameters = (await self.client.get("/openapi.json")).json()["paths"][
      "/api/threads"
    ]["get"]["parameters"]
    limit = next(item for item in parameters if item["name"] == "limit")
    self.assertTrue(limit["required"])
    self.assertEqual(limit["schema"]["type"], "integer")

  async def test_python_callers_choose_page_size_and_reject_invalid_limits(self):
    ids = await self._seed_equal_time_threads(27)
    first = await self.store.list_threads(limit=4)
    self.assertEqual([row["id"] for row in first["data"]], list(reversed(ids))[:4])
    second = await self.runtime.threads.list_threads(
      limit=23, cursor=first["next_cursor"]
    )
    self.assertEqual([row["id"] for row in second["data"]], list(reversed(ids))[4:])
    self.assertIsNone(second["next_cursor"])
    for caller in (self.store, self.runtime.threads):
      for limit in (0, -1, True, 1.5, "20"):
        with self.subTest(caller=type(caller).__name__, limit=limit):
          with self.assertRaisesRegex(ValueError, "positive integer"):
            await caller.list_threads(limit=limit)

  async def test_status_summary_covers_all_run_states_and_prefers_active_run(self):
    transitions = RunTransitions(self.store)
    expectations = {"empty": (None, None)}
    await self.store.create_thread("empty")

    for status in ("running", "interrupted", "completed", "cancelled", "error"):
      thread_id = f"thread-{status}"
      run_id = f"run-{status}"
      await self.store.create_thread(thread_id)
      await transitions.create_run(
        thread_id=thread_id,
        run_id=run_id,
        entry_message=HumanMessage(id=f"human-{status}", content=status),
      )
      if status == "interrupted":
        outcome = ExecutionOutcome(
          ExecutionReason.INTERRUPTED,
          pause=ExecutionPause(
            checkpoint={
              "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": "",
                "checkpoint_id": f"checkpoint-{status}",
              }
            },
            interrupts=({"id": "approval", "namespace": "", "value": {}},),
          ),
        )
        await transitions.settle_execution(
          thread_id=thread_id, run_id=run_id, outcome=outcome
        )
      elif status == "completed":
        await transitions.settle_execution(
          thread_id=thread_id,
          run_id=run_id,
          outcome=ExecutionOutcome(ExecutionReason.COMPLETED),
        )
      elif status == "cancelled":
        await transitions.cancel_run(thread_id=thread_id, run_id=run_id)
      elif status == "error":
        await transitions.settle_execution(
          thread_id=thread_id,
          run_id=run_id,
          outcome=ExecutionOutcome(ExecutionReason.FAILED, error=ValueError("failed")),
        )
      expectations[thread_id] = (run_id, status)

    page = (await self.client.get("/api/threads", params={"limit": 20})).json()
    rows = {row["id"]: row for row in page["data"]}
    self.assertEqual(set(rows), set(expectations))
    for thread_id, (run_id, status) in expectations.items():
      with self.subTest(thread_id=thread_id):
        self.assertEqual(
          (rows[thread_id]["run_id"], rows[thread_id]["run_status"]), (run_id, status)
        )

    # Even if timestamps and UUID order disagree, an active run outranks a terminal row.
    await self.store.create_thread("active-preferred")
    await transitions.create_run(
      thread_id="active-preferred",
      run_id="z-terminal",
      entry_message=HumanMessage(id="human-terminal", content="old"),
    )
    await transitions.settle_execution(
      thread_id="active-preferred",
      run_id="z-terminal",
      outcome=ExecutionOutcome(ExecutionReason.COMPLETED),
    )
    await transitions.create_run(
      thread_id="active-preferred",
      run_id="a-active",
      entry_message=HumanMessage(id="human-active", content="new"),
    )
    connection = await aiosqlite.connect(self.path)
    try:
      await connection.execute(
        "UPDATE runs SET created_at = ? WHERE id = ?",
        ("2099-01-01T00:00:00+00:00", "z-terminal"),
      )
      await connection.commit()
    finally:
      await connection.close()
    active = {
      row["id"]: row
      for row in (await self.client.get("/api/threads", params={"limit": 20})).json()[
        "data"
      ]
    }["active-preferred"]
    self.assertEqual((active["run_id"], active["run_status"]), ("a-active", "running"))

  async def test_run_running_sequence_beats_equal_created_at_and_late_old_settlement(
    self,
  ):
    await self.store.create_thread("sequence-order")
    transitions = RunTransitions(self.store)
    for run_id, human_id in (("z-old", "human-old"), ("a-new", "human-new")):
      await transitions.create_run(
        thread_id="sequence-order",
        run_id=run_id,
        entry_message=HumanMessage(id=human_id, content=run_id),
      )
      await transitions.settle_execution(
        thread_id="sequence-order",
        run_id=run_id,
        outcome=ExecutionOutcome(ExecutionReason.COMPLETED),
      )

    connection = await aiosqlite.connect(self.path)
    try:
      await connection.execute(
        "UPDATE runs SET created_at = ? WHERE id IN (?, ?)",
        (_FIXED_TIME, "z-old", "a-new"),
      )
      await connection.commit()
    finally:
      await connection.close()

    # Late usage settlement for the older execution must not make it the latest run.
    await transitions.settle_execution(
      thread_id="sequence-order",
      run_id="z-old",
      outcome=ExecutionOutcome(ExecutionReason.COMPLETED),
      usage={
        "total_input": 0,
        "total_output": 0,
        "total_tokens": 0,
        "calls": 0,
        "by_model": {},
      },
    )
    response = await self.client.get("/api/threads", params={"limit": 20})
    row = next(
      item for item in response.json()["data"] if item["id"] == "sequence-order"
    )
    self.assertEqual((row["run_id"], row["run_status"]), ("a-new", "completed"))

  async def test_reads_and_live_delta_do_not_touch_thread_sort_time(self):
    await self.store.create_thread("read-only")
    before = next(
      row
      for row in (await self.store.list_threads(limit=20))["data"]
      if row["id"] == "read-only"
    )
    for _ in range(2):
      response = await self.client.get("/api/threads", params={"limit": 20})
      self.assertEqual(response.status_code, 200)
      self.assertEqual(response.headers.get("cache-control"), "no-store")
    after_reads = next(
      row
      for row in (await self.store.list_threads(limit=20))["data"]
      if row["id"] == "read-only"
    )
    self.assertEqual(after_reads["updated_at"], before["updated_at"])

    self.runtime.runs.agent = _BlockedDeltaAgent()
    execution = await self.runtime.runs.start_run("read-only", "test delta")
    started = next(
      row
      for row in (await self.store.list_threads(limit=20))["data"]
      if row["id"] == "read-only"
    )
    subscription = execution.stream.subscribe()
    try:
      while True:
        event = await asyncio.wait_for(subscription.__anext__(), 2)
        if event.event == "message":
          break
    finally:
      await subscription.aclose()
    after_delta = next(
      row
      for row in (await self.store.list_threads(limit=20))["data"]
      if row["id"] == "read-only"
    )
    self.assertEqual(after_delta["updated_at"], started["updated_at"])
    listed = next(
      row
      for row in (await self.client.get("/api/threads", params={"limit": 20})).json()[
        "data"
      ]
      if row["id"] == "read-only"
    )
    self.assertEqual(listed["updated_at"], started["updated_at"])
    await self.runtime.runs.cancel_run("read-only", execution.run_id)
    cancelled = await self.runtime.runs.wait_run(execution)
    self.assertEqual(cancelled["status"], RunStatus.CANCELLED)

  async def test_status_and_sort_time_commit_together_and_rollback_releases_shared_lock(
    self,
  ):
    reader = await ChatStore.open(self.path)
    self.addAsyncCleanup(reader.close)
    await self.store.create_thread("transaction")
    await self._set_thread_updated_at("transaction", _FIXED_TIME)
    transitions = RunTransitions(self.store)
    await transitions.create_run(
      thread_id="transaction",
      run_id="run",
      entry_message=HumanMessage(id="human", content="hello"),
    )
    await self._set_thread_updated_at("transaction", _FIXED_TIME)

    commit_entered, allow_commit = asyncio.Event(), asyncio.Event()
    original_commit = self.store._connection.commit

    async def held_commit():
      commit_entered.set()
      await allow_commit.wait()
      await original_commit()

    with patch.object(self.store._connection, "commit", side_effect=held_commit):
      settling = asyncio.create_task(
        transitions.settle_execution(
          thread_id="transaction",
          run_id="run",
          outcome=ExecutionOutcome(ExecutionReason.COMPLETED),
        )
      )
      await asyncio.wait_for(commit_entered.wait(), 2)
      same_connection_read = asyncio.create_task(self.store.list_threads(limit=20))
      await asyncio.sleep(0.02)
      self.assertFalse(same_connection_read.done())
      before_commit = next(
        row
        for row in (await reader.list_threads(limit=20))["data"]
        if row["id"] == "transaction"
      )
      self.assertEqual(
        (before_commit["run_status"], before_commit["updated_at"]),
        ("running", _FIXED_TIME),
      )
      allow_commit.set()
      await settling
      committed_read = await same_connection_read

    after_commit = next(
      row
      for row in (await reader.list_threads(limit=20))["data"]
      if row["id"] == "transaction"
    )
    same_connection_row = next(
      row for row in committed_read["data"] if row["id"] == "transaction"
    )
    self.assertEqual(
      (after_commit["run_status"], after_commit["updated_at"]),
      ("completed", same_connection_row["updated_at"]),
    )
    self.assertGreater(after_commit["updated_at"], _FIXED_TIME)

    await self.store.create_thread("rollback")
    await self._set_thread_updated_at("rollback", _FIXED_TIME)
    with patch.object(
      self.store._connection, "commit", side_effect=OSError("commit failed")
    ):
      with self.assertRaisesRegex(OSError, "commit failed"):
        await transitions.create_run(
          thread_id="rollback",
          run_id="rolled-back-run",
          entry_message=HumanMessage(id="rolled-back-human", content="rollback"),
        )
    rollback_row = next(
      row
      for row in (await reader.list_threads(limit=20))["data"]
      if row["id"] == "rollback"
    )
    self.assertEqual(
      (rollback_row["run_id"], rollback_row["run_status"], rollback_row["updated_at"]),
      (None, None, _FIXED_TIME),
    )
    self.assertIsNone(await self.store.get_run("rolled-back-run", "rollback"))

  async def test_invalid_storage_is_503_retryable_or_500_without_mutating_rows(self):
    await self.store.create_thread("durable")
    before = (await self.client.get("/api/threads", params={"limit": 20})).json()
    busy = sqlite3.OperationalError("database is locked")
    busy.sqlite_errorcode = sqlite3.SQLITE_BUSY
    corrupt = sqlite3.DatabaseError("database disk image is malformed")
    corrupt.sqlite_errorcode = sqlite3.SQLITE_CORRUPT
    for error, status in ((busy, 503), (corrupt, 500)):
      with self.subTest(status=status):
        with patch.object(aiosqlite.Connection, "execute", side_effect=error):
          response = await self.client.get("/api/threads", params={"limit": 20})
        self.assertEqual(response.status_code, status)
        self.assertEqual(response.headers.get("cache-control"), "no-store")
        if status == 503:
          self.assertEqual(response.headers.get("retry-after"), "1")
        else:
          self.assertIsNone(response.headers.get("retry-after"))
        self.assertEqual(
          (await self.client.get("/api/threads", params={"limit": 20})).json(), before
        )


if __name__ == "__main__":
  unittest.main()
