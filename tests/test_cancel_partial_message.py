"""取消保存的公开 Runtime/HTTP 事实与事务故障边界。"""

import asyncio
import json
import sqlite3
import tempfile
import unittest
from contextlib import asynccontextmanager, closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from langchain_core.messages import AIMessage, AIMessageChunk
from shikigen.app_config import AppConfig, McpConfig, ModelConfig
from shikigen.contracts.messages import message_content, normalize_message
from shikigen.contracts.runs import MessageConflict
from shikigen.core.execution import ExecutionRegistry
from shikigen.persistence import ChatStore
from shikigen.runtime.composition import assemble_runtime
from shikigen.runtime.run_events import RunEventIngestor

from app.server import app


class PausingGraph:
  checkpointer = None

  def __init__(self, *, complete_first=False, pause=False, hold_first=False):
    self.ready = asyncio.Event()
    self.release = asyncio.Event()
    self.complete_first = complete_first
    self.pause = pause
    self.hold_first = hold_first
    if pause:
      self.checkpointer = True

  async def astream_events(self, value, **kwargs):
    self.coordinate = {
      "configurable": {
        "thread_id": kwargs["config"]["configurable"]["thread_id"],
        "checkpoint_ns": "",
        "checkpoint_id": "partial-pause",
      }
    }

    async def events():
      if self.hold_first:
        self.ready.set()
        await self.release.wait()
      yield {"method": "values", "params": {"namespace": [], "data": value}}
      for identity, text in [("a", "  开始\n"), ("b", "\n"), ("a", "    后续 ")]:
        yield {
          "method": "messages",
          "params": {
            "namespace": [],
            "data": [AIMessageChunk(id=identity, content=text)],
          },
        }
      if self.complete_first:
        yield {
          "method": "values",
          "params": {
            "namespace": [],
            "data": {"messages": [AIMessage(id="a", content="完整回答")]},
          },
        }
      self.ready.set()
      await self.release.wait()
      if self.pause:
        yield {
          "method": "checkpoints",
          "params": {"namespace": [], "data": {"config": self.coordinate}},
        }
        return
      yield {
        "method": "values",
        "params": {
          "namespace": [],
          "data": {"messages": [AIMessage(id="a", content="迟到的完整回答")]},
        },
      }

    @asynccontextmanager
    async def stream():
      yield events()

    return stream()

  async def aget_state(self, config, **kwargs):
    return SimpleNamespace(
      config=self.coordinate,
      next=("tool",),
      interrupts=(),
      tasks=[
        SimpleNamespace(
          state=None,
          interrupts=[
            SimpleNamespace(
              id="approval-id",
              value={"action_requests": [{"name": "bash", "args": {}}]},
            )
          ],
        )
      ],
    )


class CancelPartialMessageTests(unittest.IsolatedAsyncioTestCase):
  async def asyncSetUp(self):
    directory = tempfile.TemporaryDirectory()
    self.addCleanup(directory.cleanup)
    self.path = Path(directory.name) / "chat.db"
    self.store = await ChatStore.open(self.path)
    self.addAsyncCleanup(self.store.close)

  async def start(self, **kwargs):
    self.graph = PausingGraph(**kwargs)
    registry = ExecutionRegistry()
    self.ingestor = RunEventIngestor(self.store, registry)
    self.runtime = assemble_runtime(
      config=AppConfig(model=ModelConfig(), mcp=McpConfig()),
      agent=self.graph,
      chat_store=self.store,
      executions=registry,
      ingestor=self.ingestor,
    )
    self.addAsyncCleanup(self.runtime.lifecycle.shutdown)
    self.thread = await self.runtime.threads.create_thread()
    self.execution = await self.runtime.runs.start_run(self.thread, "原文")
    self.run_id = self.execution.run_id
    await asyncio.wait_for(self.graph.ready.wait(), 3)

  async def test_cancel_snapshot_commits_all_received_text_with_original_sequences(
    self,
  ):
    await self.start()
    before = await self.runtime.runs.list_run_messages(self.thread, self.run_id)
    self.assertEqual(len(before), 1, "GET 不补写预览")
    observation = await self.runtime.runs.observe_run(self.thread, self.run_id)
    result = await self.runtime.runs.cancel_run(self.thread, self.run_id)
    self.assertEqual(result["status"], "cancelled")
    messages = await self.runtime.runs.list_run_messages(self.thread, self.run_id)
    self.assertEqual(
      [m["content"]["content"] for m in messages], ["原文", "  开始\n    后续 ", "\n"]
    )
    self.assertEqual(
      [m["content"]["generation_status"] for m in messages[1:]],
      ["cancelled", "cancelled"],
    )
    self.assertTrue(all(m["content"]["tool_calls"] == [] for m in messages[1:]))
    await self.runtime.runs.wait_run(self.execution)
    events = [event async for event in observation]
    preview = {
      e.data["message_id"]: e.data["seq"] for e in events if e.event == "message"
    }
    self.assertEqual([m["seq"] for m in messages[1:]], [preview["a"], preview["b"]])
    self.assertEqual(
      await self.runtime.runs.cancel_run(self.thread, self.run_id),
      await self.runtime.runs.get_run_snapshot(self.thread, self.run_id),
    )
    self.assertEqual(
      await self.runtime.runs.list_run_messages(self.thread, self.run_id), messages
    )
    reopened = await ChatStore.open(self.path)
    try:
      self.assertEqual(
        await reopened.list_messages_by_run(self.thread, self.run_id), messages
      )
    finally:
      await reopened.close()

  async def test_rollback_preserves_buffer_and_retry_commits_once(self):
    await self.start()
    before = await self.runtime.runs.list_run_events(self.thread, self.run_id)
    original = self.store._events.insert_fact

    async def fail(*args):
      if args[2] == "run_cancelled":
        raise OSError("fault after partial messages")
      await original(*args)

    with patch.object(self.store._events, "insert_fact", side_effect=fail):
      with self.assertRaises(OSError):
        await self.runtime.runs.cancel_run(self.thread, self.run_id)
    self.assertEqual(
      await self.runtime.runs.list_run_events(self.thread, self.run_id), before
    )
    self.assertEqual(
      (await self.runtime.runs.get_run_snapshot(self.thread, self.run_id))["status"],
      "running",
    )
    self.assertFalse(self.execution.abort_event.is_set())
    self.assertIs(self.runtime.executions.get(self.thread, self.run_id), self.execution)
    await self.runtime.runs.cancel_run(self.thread, self.run_id)
    await self.runtime.runs.wait_run(self.execution)
    self.assertEqual(
      [
        m["content"]["content"]
        for m in await self.runtime.runs.list_run_messages(self.thread, self.run_id)
      ],
      ["原文", "  开始\n    后续 ", "\n"],
    )

  async def test_complete_message_wins_and_late_graph_replay_stays_in_original_run(
    self,
  ):
    await self.start(complete_first=True)
    await self.runtime.runs.cancel_run(self.thread, self.run_id)
    await self.runtime.runs.wait_run(self.execution)
    messages = await self.runtime.runs.list_run_messages(self.thread, self.run_id)
    self.assertEqual(messages[1]["content"]["generation_status"], "complete")
    self.assertEqual(messages[1]["content"]["content"], "完整回答")
    self.assertEqual(messages[2]["content"]["generation_status"], "cancelled")
    # 下一根快照重放已封存 b，不能归给新 Run 或覆盖其正文。
    self.graph = PausingGraph()

    async def replay(value, **kwargs):
      async def events():
        yield {
          "method": "values",
          "params": {
            "namespace": [],
            "data": {
              "messages": [*value["messages"], AIMessage(id="b", content="迟到内容")]
            },
          },
        }

      @asynccontextmanager
      async def stream():
        yield events()

      return stream()

    self.runtime.agent.astream_events = replay
    next_run = await self.runtime.runs.start_run(self.thread, "下一任务")
    self.assertEqual(
      (await self.runtime.runs.wait_run(next_run))["status"], "completed"
    )
    self.assertEqual(
      len(await self.runtime.runs.list_run_messages(self.thread, next_run.run_id)), 1
    )
    self.assertEqual(
      await self.runtime.runs.list_run_messages(self.thread, self.run_id), messages
    )

  async def test_http_cancel_response_and_reopen_history_contain_same_committed_body(
    self,
  ):
    await self.start()
    with patch.object(app.state, "runtime", self.runtime, create=True):
      async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
      ) as client:
        path = f"/api/threads/{self.thread}/runs/{self.run_id}"
        response = await client.post(path + "/cancel")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["status"], "cancelled")
        messages = (await client.get(path + "/messages")).json()["data"]
        history = (await client.get(f"/api/threads/{self.thread}/messages")).json()[
          "data"
        ]
        self.assertEqual(
          [m["content"] for m in messages], [m["content"] for m in history]
        )
        self.assertEqual(messages[-2]["content"]["content"], "  开始\n    后续 ")
        replay = await client.get(path + "/stream")
        self.assertIn('"generation_status":"cancelled"', replay.text)
    await self.runtime.runs.wait_run(self.execution)

  async def test_legacy_complete_is_idempotent_and_conflicts_fail(
    self,
  ):
    await self.start(complete_first=True)
    legacy = {"type": "ai", "message_id": "a", "content": "完整回答", "tool_calls": []}
    # 历史库夹具：模拟升级前已保存的缺省 complete。断言仍只走公开接口。
    with closing(sqlite3.connect(self.path)) as legacy_database:
      with legacy_database:
        legacy_database.execute(
          "UPDATE run_events SET content_json = ? "
          "WHERE thread_id = ? AND event_key = 'ai:a'",
          (json.dumps(legacy, ensure_ascii=False), self.thread),
        )
    original = await self.runtime.runs.list_run_messages(self.thread, self.run_id)
    self.assertNotIn("generation_status", original[1]["content"])
    self.assertEqual(normalize_message(legacy)["generation_status"], "complete")
    existing = await self.store.append_message(
      thread_id=self.thread, run_id=self.run_id, content=legacy
    )
    repeated = await self.store.append_message(
      thread_id=self.thread,
      run_id=self.run_id,
      content=message_content(AIMessage(id="a", content="完整回答")),
    )
    self.assertEqual(existing.event, repeated.event)
    with self.assertRaises(MessageConflict):
      await self.store.append_message(
        thread_id=self.thread,
        run_id=self.run_id,
        content={**legacy, "content": "changed"},
      )
    with self.assertRaises(ValueError):
      normalize_message({**legacy, "generation_status": "unknown"})
    await self.runtime.runs.cancel_run(self.thread, self.run_id)

  async def test_paused_text_survives_handle_removal_and_cancel_rollback(self):
    await self.start(pause=True)
    self.graph.release.set()
    self.assertEqual(
      (await self.runtime.runs.wait_run(self.execution))["status"], "interrupted"
    )
    self.assertIsNone(self.runtime.executions.get(self.thread, self.run_id))
    before = await self.runtime.runs.list_run_events(self.thread, self.run_id)
    self.assertEqual(
      len(await self.runtime.runs.list_run_messages(self.thread, self.run_id)), 1
    )
    original = self.store._events.insert_fact

    async def fail(*args):
      if args[2] == "run_cancelled":
        raise OSError("paused cancellation rollback")
      await original(*args)

    with patch.object(self.store._events, "insert_fact", side_effect=fail):
      with self.assertRaises(OSError):
        await self.runtime.runs.cancel_run(self.thread, self.run_id)
    self.assertEqual(
      await self.runtime.runs.list_run_events(self.thread, self.run_id), before
    )
    result = await self.runtime.runs.cancel_run(self.thread, self.run_id)
    self.assertEqual(result["status"], "cancelled")
    messages = await self.runtime.runs.list_run_messages(self.thread, self.run_id)
    self.assertEqual(
      [m["content"]["content"] for m in messages], ["原文", "  开始\n    后续 ", "\n"]
    )
    events = await self.runtime.runs.list_run_events(self.thread, self.run_id)
    self.assertEqual(
      [e["event_type"] for e in events[-2:]], ["approval_invalidated", "run_cancelled"]
    )

  async def test_cancel_barrier_blocks_late_delta_and_ignores_late_facts(self):
    await self.start()
    entered, release = asyncio.Event(), asyncio.Event()
    original = self.store._events.insert_fact

    async def delayed(*args):
      if args[2] == "run_cancelled":
        entered.set()
        await release.wait()
      await original(*args)

    with patch.object(self.store._events, "insert_fact", side_effect=delayed):
      cancel = asyncio.create_task(
        self.runtime.runs.cancel_run(self.thread, self.run_id)
      )
      await asyncio.wait_for(entered.wait(), 3)
      late = asyncio.create_task(
        self.ingestor.ingest_delta(
          {"message_id": "a", "text": "迟到片段", "done": False},
          thread_id=self.thread,
          run_id=self.run_id,
        )
      )
      snapshot = asyncio.create_task(
        self.runtime.runs.get_run_snapshot(self.thread, self.run_id)
      )
      await asyncio.sleep(0)
      self.assertFalse(late.done())
      self.assertFalse(snapshot.done(), "纯 GET 不暴露未提交取消")
      release.set()
      self.assertEqual((await cancel)["status"], "cancelled")
      await late
      self.assertEqual((await snapshot)["status"], "cancelled")
    await self.runtime.runs.wait_run(self.execution)
    before = await self.runtime.runs.list_run_events(self.thread, self.run_id)
    await self.ingestor.ingest_delta(
      {"message_id": "new-late", "text": "不能新增", "done": False},
      thread_id=self.thread,
      run_id=self.run_id,
    )
    await self.ingestor.ingest_message(
      message_content(AIMessage(id="a", content="不能覆盖")),
      thread_id=self.thread,
      run_id=self.run_id,
    )
    await self.ingestor.ingest_message(
      message_content(AIMessage(id="new-late", content="不能新增")),
      thread_id=self.thread,
      run_id=self.run_id,
    )
    self.assertEqual(
      await self.runtime.runs.list_run_events(self.thread, self.run_id), before
    )
    self.assertEqual(
      [
        m["content"]["content"]
        for m in await self.runtime.runs.list_run_messages(self.thread, self.run_id)
      ],
      ["原文", "  开始\n    后续 ", "\n"],
    )

  async def test_cancel_before_first_event_seals_delta_and_complete_ingestion(self):
    await self.start(hold_first=True)
    observation = await self.runtime.runs.observe_run(self.thread, self.run_id)
    entered, release = asyncio.Event(), asyncio.Event()
    original = self.store._events.insert_fact

    async def delayed(*args):
      if args[2] == "run_cancelled":
        entered.set()
        await release.wait()
      await original(*args)

    with patch.object(self.store._events, "insert_fact", side_effect=delayed):
      cancel = asyncio.create_task(
        self.runtime.runs.cancel_run(self.thread, self.run_id)
      )
      await asyncio.wait_for(entered.wait(), 3)
      delta = asyncio.create_task(
        self.ingestor.ingest_delta(
          {"message_id": "first-late", "text": "取消后首片段", "done": False},
          thread_id=self.thread,
          run_id=self.run_id,
        )
      )
      complete = asyncio.create_task(
        self.ingestor.ingest_message(
          message_content(AIMessage(id="first-late", content="取消后首完整消息")),
          thread_id=self.thread,
          run_id=self.run_id,
        )
      )
      await asyncio.sleep(0)
      self.assertFalse(delta.done())
      self.assertFalse(complete.done())
      release.set()
      self.assertEqual((await cancel)["status"], "cancelled")
      await asyncio.gather(delta, complete)
    await self.runtime.runs.wait_run(self.execution)
    self.assertEqual(
      len(await self.runtime.runs.list_run_messages(self.thread, self.run_id)), 1
    )
    events = [event async for event in observation]
    self.assertFalse(any(event.event == "message" for event in events))

  async def test_completion_barrier_seals_before_queued_delta_can_mutate_facts(self):
    await self.start()
    entered, release = asyncio.Event(), asyncio.Event()
    original = self.store._events.insert_fact

    async def delayed(*args):
      if args[2] == "run_completed":
        entered.set()
        await release.wait()
      await original(*args)

    with patch.object(self.store._events, "insert_fact", side_effect=delayed):
      self.graph.release.set()
      await asyncio.wait_for(entered.wait(), 3)
      before = asyncio.create_task(
        self.runtime.runs.list_run_messages(self.thread, self.run_id)
      )
      late = asyncio.create_task(
        self.ingestor.ingest_delta(
          {"message_id": "new-late", "text": "完成后的片段", "done": False},
          thread_id=self.thread,
          run_id=self.run_id,
        )
      )
      await asyncio.sleep(0)
      self.assertFalse(late.done())
      self.assertFalse(before.done())
      release.set()
      self.assertEqual(
        (await self.runtime.runs.wait_run(self.execution))["status"], "completed"
      )
      await late
      messages = await before
    self.assertEqual(
      await self.runtime.runs.list_run_messages(self.thread, self.run_id), messages
    )
    self.assertFalse(any(m["content"]["message_id"] == "new-late" for m in messages))

  async def test_disconnected_cancel_caller_still_saves_text_and_terminal_once(self):
    await self.start()
    entered, release = asyncio.Event(), asyncio.Event()
    original = self.runtime.runs._transitions.cancel_run_in_transaction

    async def delayed(*args, **kwargs):
      entered.set()
      await release.wait()
      return await original(*args, **kwargs)

    with patch.object(
      self.runtime.runs._transitions, "cancel_run_in_transaction", side_effect=delayed
    ):
      with patch.object(app.state, "runtime", self.runtime, create=True):
        async with httpx.AsyncClient(
          transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
          path = f"/api/threads/{self.thread}/runs/{self.run_id}"
          caller = asyncio.create_task(client.post(path + "/cancel"))
          await asyncio.wait_for(entered.wait(), 3)
          caller.cancel()
          with self.assertRaises(asyncio.CancelledError):
            await caller
          release.set()
          for _ in range(200):
            snapshot = (await client.get(path)).json()["data"]
            if snapshot["status"] == "cancelled":
              break
            await asyncio.sleep(0.01)
          self.assertEqual(snapshot["status"], "cancelled")
          messages = (await client.get(path + "/messages")).json()["data"]
          self.assertEqual(
            [m["content"]["content"] for m in messages],
            ["原文", "  开始\n    后续 ", "\n"],
          )
    await self.runtime.runs.wait_run(self.execution)
    events = await self.runtime.runs.list_run_events(self.thread, self.run_id)
    self.assertEqual(sum(e["event_type"] == "run_cancelled" for e in events), 1)
