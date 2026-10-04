"""会话打开链路：通过公开 HTTP / Runtime 读取已提交事实。"""

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import aiosqlite
import httpx
from shikigen.app_config import AppConfig, McpConfig, ModelConfig
from shikigen.persistence import ChatStore
from shikigen.runtime.composition import assemble_runtime
from test_loop import FailingAgent, MessageAgent

from app.server import create_app


class ConversationQueryTests(unittest.IsolatedAsyncioTestCase):
  async def asyncSetUp(self):
    self.directory = tempfile.TemporaryDirectory()
    self.addCleanup(self.directory.cleanup)
    self.store = await ChatStore.open(Path(self.directory.name) / "runs.db")
    self.addAsyncCleanup(self.store.close)
    self.runtime = assemble_runtime(
      config=AppConfig(model=ModelConfig(), mcp=McpConfig()),
      agent=MessageAgent(),
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

  async def test_history_retains_records_and_projects_each_runs_current_status(self):
    thread = (await self.client.post("/api/threads")).json()["thread_id"]
    path = f"/api/threads/{thread}/messages"
    empty = await self.client.get(path)
    self.assertEqual(empty.json(), {"data": []})
    self.assertEqual(empty.headers.get("cache-control"), "no-store")
    first = await self.runtime.runs.start_run(thread, "第一轮")
    await self.runtime.runs.wait_run(first)
    self.runtime.runs.agent = FailingAgent()
    second = await self.runtime.runs.start_run(thread, "第二轮")
    await self.runtime.runs.wait_run(second)

    result = await self.client.get(path)
    history = result.json()["data"]
    self.assertEqual(result.status_code, 200)
    self.assertEqual(history, await self.runtime.threads.list_thread_messages(thread))
    originals = await self.store.list_thread_messages(thread)
    self.assertEqual(
      history,
      [
        {
          **item,
          "run_status": "completed" if item["run_id"] == first.run_id else "error",
        }
        for item in originals
      ],
    )
    self.assertEqual(history[-1]["run_id"], second.run_id)
    self.assertEqual([m["seq"] for m in history], sorted(m["seq"] for m in history))
    self.assertEqual(
      (await self.client.get("/api/threads/missing/messages")).status_code, 404
    )

  async def test_snapshot_reads_committed_pause_without_recovery_or_writes(self):
    from langchain_core.messages import HumanMessage
    from shikigen.runtime.runs import RunTransitions

    thread = await self.runtime.threads.create_thread()
    await RunTransitions(self.store).create_run(
      thread_id=thread,
      run_id="paused",
      entry_message=HumanMessage(id="h", content="hi"),
    )
    # 模拟暂停事实可读、但 checkpoint / 审批恢复资料损坏的存量数据。
    async with self.store.transaction() as tx:
      await tx.runs.update_state("paused", thread, status="interrupted", terminal=False)
    before = await self.runtime.runs.list_run_events(thread, "paused")
    threads_before = await self.runtime.threads.list_threads()
    path = f"/api/threads/{thread}/runs/paused"
    for _ in range(2):
      response = await self.client.get(path)
      self.assertEqual(response.status_code, 200)
      self.assertEqual(response.headers.get("cache-control"), "no-store")
      snapshot = response.json()["data"]
      self.assertEqual(
        snapshot, await self.runtime.runs.get_run_snapshot(thread, "paused")
      )
      self.assertEqual(
        (snapshot["id"], snapshot["thread_id"], snapshot["status"]),
        ("paused", thread, "interrupted"),
      )
      self.assertIsNone(snapshot["usage"])
      self.assertIsNone(snapshot["completed_at"])
      self.assertEqual(
        (await self.client.get(f"/api/threads/{thread}/messages")).json()["data"][0][
          "run_status"
        ],
        "interrupted",
      )
    self.assertEqual(before, await self.runtime.runs.list_run_events(thread, "paused"))
    self.assertEqual(threads_before, await self.runtime.threads.list_threads())
    for target in (
      f"/api/threads/{thread}/runs/missing",
      "/api/threads/other/runs/paused",
    ):
      self.assertEqual((await self.client.get(target)).status_code, 404)

  async def test_unavailable_and_corrupt_reads_never_change_run_facts(self):
    thread = await self.runtime.threads.create_thread()
    execution = await self.runtime.runs.start_run(thread, "持久结果")
    expected = await self.runtime.runs.wait_run(execution)
    facts = await self.runtime.runs.list_run_events(thread, execution.run_id)
    snapshot_path = f"/api/threads/{thread}/runs/{execution.run_id}"
    paths = (f"/api/threads/{thread}/messages", snapshot_path)
    busy = sqlite3.OperationalError("database is locked")
    busy.sqlite_errorcode = sqlite3.SQLITE_BUSY
    corrupt = sqlite3.DatabaseError("database disk image is malformed")
    corrupt.sqlite_errorcode = sqlite3.SQLITE_CORRUPT
    for error, status in ((busy, 503), (corrupt, 500)):
      for path in paths:
        with self.subTest(path=path, status=status):
          # 故障注入位于 SQLite 驱动边界；查询后仍从公开接口核实原事实。
          with patch.object(aiosqlite.Connection, "execute", side_effect=error):
            response = await self.client.get(path)
          self.assertEqual(response.status_code, status)
          self.assertEqual(response.headers.get("cache-control"), "no-store")
          if status == 503:
            self.assertEqual(response.headers.get("retry-after"), "1")
          self.assertEqual(
            (await self.client.get(snapshot_path)).json()["data"], expected
          )
          self.assertEqual(
            await self.runtime.runs.list_run_events(thread, execution.run_id), facts
          )


if __name__ == "__main__":
  unittest.main()
