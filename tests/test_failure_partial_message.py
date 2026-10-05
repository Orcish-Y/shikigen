"""真实执行失败通过 Runtime、HTTP 和持久查询保留已接入正文。"""

import asyncio
import sqlite3
import tempfile
import unittest
from contextlib import asynccontextmanager, closing
from pathlib import Path
from unittest.mock import patch

import httpx
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
from shikigen.app_config import AppConfig, McpConfig, ModelConfig
from shikigen.contracts.messages import message_content
from shikigen.core.execution import ExecutionOutcome, ExecutionReason, ExecutionRegistry
from shikigen.persistence import ChatStore
from shikigen.runtime.composition import assemble_runtime
from shikigen.runtime.run_events import RunEventIngestor
from shikigen.runtime.runs import RunTransitions
from test_cancel_partial_message import PausingGraph

from app.server import app

ERROR = "供应商执行失败\n  原始原因：request-123 "


class FailureGraph:
  checkpointer = None

  def __init__(self):
    self.ready = asyncio.Event()
    self.release = asyncio.Event()
    self.calls = 0
    self.parts = [("a", "  开始\n"), ("b", "\n"), ("a", "    后续 ")]
    self.committed = []
    self.fail = True
    self.replay = False

  async def astream_events(self, value, **kwargs):
    self.calls += 1

    async def events():
      if self.replay:
        yield {
          "method": "values",
          "params": {
            "namespace": [],
            "data": {
              "messages": [
                *value["messages"],
                AIMessage(id="a", content="根快照重放"),
                AIMessage(id="b", content="不能归给新运行"),
              ]
            },
          },
        }
        return
      yield {"method": "values", "params": {"namespace": [], "data": value}}
      if self.committed:
        yield {
          "method": "values",
          "params": {"namespace": [], "data": {"messages": self.committed}},
        }
      for identity, text in self.parts:
        yield {
          "method": "messages",
          "params": {
            "namespace": [],
            "data": [AIMessageChunk(id=identity, content=text)],
          },
        }
      self.ready.set()
      await self.release.wait()
      if self.fail:
        raise RuntimeError(ERROR)

    @asynccontextmanager
    async def stream():
      yield events()

    return stream()


class FailurePartialMessageTests(unittest.IsolatedAsyncioTestCase):
  async def asyncSetUp(self):
    directory = tempfile.TemporaryDirectory()
    self.addCleanup(directory.cleanup)
    self.path = Path(directory.name) / "chat.db"
    self.store = await ChatStore.open(self.path)
    self.addAsyncCleanup(self.store.close)
    self.graph = FailureGraph()
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

  async def start(self):
    self.execution = await self.runtime.runs.start_run(self.thread, "原文")
    self.run_id = self.execution.run_id
    await asyncio.wait_for(self.graph.ready.wait(), 3)

  async def test_execution_failure_saves_all_text_identity_sequence_and_error(self):
    await self.start()
    observation = await self.runtime.runs.observe_run(self.thread, self.run_id)
    before = await self.runtime.runs.list_run_messages(self.thread, self.run_id)
    self.assertEqual(len(before), 1, "查询不保存预览")
    self.graph.release.set()
    result = await self.runtime.runs.wait_run(self.execution)
    self.assertEqual(result["status"], "error")
    self.assertEqual(result["error"], ERROR)
    self.assertEqual(result["error_code"], "execution_failed")
    messages = await self.runtime.runs.list_run_messages(self.thread, self.run_id)
    self.assertEqual(
      [m["content"]["content"] for m in messages],
      ["原文", "  开始\n    后续 ", "\n"],
    )
    self.assertEqual([m["content"]["message_id"] for m in messages[1:]], ["a", "b"])
    self.assertTrue(
      all(m["content"]["generation_status"] == "error" for m in messages[1:])
    )
    self.assertTrue(all(m["content"]["tool_calls"] == [] for m in messages[1:]))
    frames = [frame async for frame in observation]
    sequences = {
      f.data["message_id"]: f.data["seq"] for f in frames if f.event == "message"
    }
    self.assertEqual([m["seq"] for m in messages[1:]], [sequences["a"], sequences["b"]])
    facts = await self.runtime.runs.list_run_events(self.thread, self.run_id)
    self.assertEqual(facts[-1]["event_type"], "run_error")
    self.assertEqual(facts[-1]["content"]["message"], ERROR)
    self.assertEqual(facts[-1]["content"]["error_code"], "execution_failed")
    self.assertEqual([f.data for f in frames if f.event == "durable_event"], facts)
    reopened = await ChatStore.open(self.path)
    try:
      self.assertEqual(
        await reopened.list_messages_by_run(self.thread, self.run_id), messages
      )
    finally:
      await reopened.close()

  async def test_storage_rollback_keeps_owner_and_retries_only_settlement(self):
    await self.start()
    original = await self.runtime.runs.list_run_events(self.thread, self.run_id)
    failure = asyncio.Event()
    frames = []

    async def observe():
      async for frame in self.execution.stream.subscribe():
        frames.append(frame)
        if frame.event == "stream_failed":
          failure.set()

    observer = asyncio.create_task(observe())
    self.addAsyncCleanup(lambda: asyncio.gather(observer, return_exceptions=True))
    with closing(sqlite3.connect(self.path)) as database:
      database.execute(
        "CREATE TRIGGER fail_error BEFORE INSERT ON run_events "
        "WHEN NEW.event_type = 'run_error' "
        "BEGIN SELECT RAISE(ABORT, 'failure settlement disk fault'); END"
      )
      database.commit()
      try:
        self.graph.release.set()
        await asyncio.wait_for(failure.wait(), 3)
        self.assertEqual(
          await self.runtime.runs.list_run_events(self.thread, self.run_id), original
        )
        self.assertEqual(
          (await self.runtime.runs.get_run_snapshot(self.thread, self.run_id))[
            "status"
          ],
          "running",
        )
        task = self.execution.task
        assert task is not None
        self.assertFalse(task.done(), "失败结果所有者必须保留以重试结算")
        self.assertIs(
          self.runtime.executions.get(self.thread, self.run_id), self.execution
        )
        self.assertFalse(any(f.event == "error" for f in frames), "回滚不能发布假终态")
        self.assertEqual(self.graph.calls, 1, "纯读不重跑模型")
      finally:
        database.execute("DROP TRIGGER fail_error")
        database.commit()
    result = await asyncio.wait_for(self.runtime.runs.wait_run(self.execution), 5)
    self.assertEqual(result["status"], "error")
    self.assertEqual(result["error"], ERROR)
    self.assertEqual(self.graph.calls, 1)
    messages = await self.runtime.runs.list_run_messages(self.thread, self.run_id)
    self.assertEqual(
      [m["content"]["content"] for m in messages], ["原文", "  开始\n    后续 ", "\n"]
    )
    await observer

  async def test_empty_text_does_not_create_empty_message(self):
    self.graph.parts = [("empty", "")]
    await self.start()
    self.graph.release.set()
    self.assertEqual(
      (await self.runtime.runs.wait_run(self.execution))["status"], "error"
    )
    self.assertEqual(
      len(await self.runtime.runs.list_run_messages(self.thread, self.run_id)), 1
    )
    facts = await self.runtime.runs.list_run_events(self.thread, self.run_id)
    self.assertEqual(
      [f["event_type"] for f in facts], ["run_running", "human_message", "run_error"]
    )

  async def test_complete_and_tool_records_are_unchanged_by_later_run_failure(self):
    self.graph.committed = [
      AIMessage(
        id="complete",
        content="完整工具请求",
        tool_calls=[{"id": "tool", "name": "read", "args": {"path": "a"}}],
      ),
      ToolMessage(
        id="result",
        tool_call_id="tool",
        content="真实工具失败",
        status="error",
        artifact={"reason": "missing file"},
      ),
    ]
    await self.start()
    before = await self.runtime.runs.list_run_messages(self.thread, self.run_id)
    self.graph.release.set()
    await self.runtime.runs.wait_run(self.execution)
    after = await self.runtime.runs.list_run_messages(self.thread, self.run_id)
    self.assertEqual(after[:3], before)
    self.assertEqual(after[1]["content"]["generation_status"], "complete")
    self.assertEqual(after[2]["content"]["status"], "error")
    self.assertEqual(after[2]["content"]["artifact"], {"reason": "missing file"})

  async def test_tool_error_and_observer_disconnect_do_not_save_failed_text(self):
    self.graph.fail = False
    self.graph.committed = [
      ToolMessage(
        id="result", tool_call_id="orphan", content="资源不存在", status="error"
      )
    ]
    await self.start()
    observation = await self.runtime.runs.observe_run(self.thread, self.run_id)
    await observation.aclose()
    before = await self.runtime.runs.list_run_messages(self.thread, self.run_id)
    self.assertEqual(len(before), 2)
    self.assertEqual(
      (await self.runtime.runs.get_run_snapshot(self.thread, self.run_id))["status"],
      "running",
    )
    self.graph.release.set()
    self.assertEqual(
      (await self.runtime.runs.wait_run(self.execution))["status"], "completed"
    )
    self.assertEqual(
      await self.runtime.runs.list_run_messages(self.thread, self.run_id), before
    )

  async def test_interrupted_is_not_failed_partial_save(self):
    paused = PausingGraph(pause=True)
    self.runtime.runs.agent = paused
    execution = await self.runtime.runs.start_run(self.thread, "审批")
    await asyncio.wait_for(paused.ready.wait(), 3)
    paused.release.set()
    self.assertEqual(
      (await self.runtime.runs.wait_run(execution))["status"], "interrupted"
    )
    self.assertEqual(
      len(await self.runtime.runs.list_run_messages(self.thread, execution.run_id)), 1
    )
    self.assertFalse(
      any(
        f["event_type"] == "run_error"
        for f in await self.runtime.runs.list_run_events(self.thread, execution.run_id)
      )
    )

  async def test_http_snapshot_history_messages_and_sse_share_saved_failure(self):
    await self.start()
    self.graph.release.set()
    await self.runtime.runs.wait_run(self.execution)
    before = await self.runtime.runs.list_run_events(self.thread, self.run_id)
    with patch.object(app.state, "runtime", self.runtime, create=True):
      async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
      ) as client:
        path = f"/api/threads/{self.thread}/runs/{self.run_id}"
        snapshot = (await client.get(path)).json()["data"]
        self.assertEqual(snapshot["error"], ERROR)
        self.assertEqual(snapshot["error_code"], "execution_failed")
        messages = (await client.get(path + "/messages")).json()["data"]
        history = (await client.get(f"/api/threads/{self.thread}/messages")).json()[
          "data"
        ]
        self.assertEqual(
          [m["content"] for m in messages], [m["content"] for m in history]
        )
        self.assertTrue(all(m["run_status"] == "error" for m in history))
        replay = await client.get(path + "/stream")
        self.assertIn('"generation_status":"error"', replay.text)
        self.assertIn('"error_code":"execution_failed"', replay.text)
    self.assertEqual(
      await self.runtime.runs.list_run_events(self.thread, self.run_id),
      before,
      "GET 不能补写",
    )
    self.assertEqual(self.graph.calls, 1)

  async def test_failed_settlement_retry_allows_cancellation_and_late_usage(self):
    await self.start()
    failed = asyncio.Event()

    async def observe():
      async for frame in self.execution.stream.subscribe():
        if frame.event == "stream_failed":
          failed.set()

    observer = asyncio.create_task(observe())
    self.addAsyncCleanup(lambda: asyncio.gather(observer, return_exceptions=True))
    with closing(sqlite3.connect(self.path)) as database:
      database.execute(
        "CREATE TRIGGER fail_error BEFORE INSERT ON run_events "
        "WHEN NEW.event_type = 'run_error' "
        "BEGIN SELECT RAISE(ABORT, 'write failed'); END"
      )
      database.commit()
      try:
        self.graph.release.set()
        await asyncio.wait_for(failed.wait(), 3)
        snapshot = await asyncio.wait_for(
          self.runtime.runs.cancel_run(self.thread, self.run_id), 2
        )
        self.assertEqual(snapshot["status"], "cancelled")
        self.assertIsNone(snapshot["error"])
        messages = await self.runtime.runs.list_run_messages(self.thread, self.run_id)
        self.assertTrue(
          all(m["content"]["generation_status"] == "cancelled" for m in messages[1:])
        )
        result = await asyncio.wait_for(self.runtime.runs.wait_run(self.execution), 5)
        self.assertEqual(result["status"], "cancelled")
        self.assertFalse(result["usage_pending"], "迟到用量仍结算")
        self.assertIsNone(result["error_code"])
        self.assertEqual(
          await self.runtime.runs.list_run_messages(self.thread, self.run_id), messages
        )
      finally:
        database.execute("DROP TRIGGER fail_error")
        database.commit()
    await observer

  async def test_failure_wins_duplicate_and_cancel_do_not_change_reason(self):
    await self.start()
    self.graph.release.set()
    original = await self.runtime.runs.wait_run(self.execution)
    facts = await self.runtime.runs.list_run_events(self.thread, self.run_id)
    self.assertEqual(
      await self.runtime.runs.cancel_run(self.thread, self.run_id), original
    )
    repeated = await RunTransitions(self.store).settle_execution(
      thread_id=self.thread,
      run_id=self.run_id,
      outcome=ExecutionOutcome(ExecutionReason.FAILED, error=ValueError("晚到原因")),
      error_code="late_error",
    )
    self.assertFalse(repeated.changed)
    self.assertEqual(repeated.error, ERROR)
    self.assertEqual(repeated.error_code, "execution_failed")
    self.assertEqual(
      await self.runtime.runs.list_run_events(self.thread, self.run_id), facts
    )

  async def test_failure_barrier_seals_late_ingestion_and_next_run_replay(self):
    await self.start()
    entered, release = asyncio.Event(), asyncio.Event()
    insert = self.store._events.insert_fact

    async def barrier(*args):
      if args[2] == "run_error":
        entered.set()
        await release.wait()
      return await insert(*args)

    with patch.object(self.store._events, "insert_fact", side_effect=barrier):
      self.graph.release.set()
      await asyncio.wait_for(entered.wait(), 3)
      late = asyncio.create_task(
        self.ingestor.ingest_delta(
          {"message_id": "a", "text": "迟到内容", "done": False},
          thread_id=self.thread,
          run_id=self.run_id,
        )
      )
      complete = asyncio.create_task(
        self.ingestor.ingest_message(
          message_content(AIMessage(id="a", content="迟到完整回答")),
          thread_id=self.thread,
          run_id=self.run_id,
        )
      )
      cancel = asyncio.create_task(
        self.runtime.runs.cancel_run(self.thread, self.run_id)
      )
      await asyncio.sleep(0)
      self.assertFalse(late.done())
      self.assertFalse(complete.done())
      self.assertFalse(cancel.done())
      release.set()
      self.assertEqual(
        (await self.runtime.runs.wait_run(self.execution))["status"], "error"
      )
      self.assertEqual((await cancel)["status"], "error")
      await asyncio.gather(late, complete)
    original = await self.runtime.runs.list_run_messages(self.thread, self.run_id)

    self.graph.replay = True
    next_run = await self.runtime.runs.start_run(self.thread, "下一任务")
    self.assertEqual(
      (await self.runtime.runs.wait_run(next_run))["status"], "completed"
    )
    self.assertEqual(
      len(await self.runtime.runs.list_run_messages(self.thread, next_run.run_id)), 1
    )
    self.assertEqual(
      await self.runtime.runs.list_run_messages(self.thread, self.run_id), original
    )

  async def test_shutdown_stops_retry_owner_without_fake_terminal(self):
    await self.start()
    failed = asyncio.Event()

    async def observe():
      async for frame in self.execution.stream.subscribe():
        if frame.event == "stream_failed":
          failed.set()

    observer = asyncio.create_task(observe())
    with closing(sqlite3.connect(self.path)) as database:
      database.execute(
        "CREATE TRIGGER fail_error BEFORE INSERT ON run_events "
        "WHEN NEW.event_type = 'run_error' "
        "BEGIN SELECT RAISE(ABORT, 'write failed'); END"
      )
      database.commit()
      self.graph.release.set()
      await asyncio.wait_for(failed.wait(), 3)
      await asyncio.wait_for(self.runtime.lifecycle.shutdown(), 2)
    await observer
    task = self.execution.task
    assert task is not None
    self.assertTrue(task.cancelled())
    self.assertIsNone(self.runtime.executions.get(self.thread, self.run_id))
    self.assertEqual(
      (await self.runtime.runs.get_run_snapshot(self.thread, self.run_id))["status"],
      "running",
    )
    self.assertEqual(
      len(await self.runtime.runs.list_run_messages(self.thread, self.run_id)), 1
    )

  async def test_start_failure_rollback_hands_off_owner_and_allows_shutdown(self):
    original_create_task = asyncio.create_task

    def cannot_start(coroutine, **kwargs):
      if kwargs.get("name", "").startswith("run:"):
        raise RuntimeError("cannot start execution")
      return original_create_task(coroutine, **kwargs)

    with closing(sqlite3.connect(self.path)) as database:
      database.execute(
        "CREATE TRIGGER fail_error BEFORE INSERT ON run_events "
        "WHEN NEW.event_type = 'run_error' "
        "BEGIN SELECT RAISE(ABORT, 'startup write failed'); END"
      )
      database.commit()
      with patch("asyncio.create_task", side_effect=cannot_start):
        with self.assertRaisesRegex(RuntimeError, "cannot start execution"):
          await asyncio.wait_for(
            self.runtime.runs.start_run(self.thread, "启动失败"), 3
          )
      messages = await self.runtime.threads.list_thread_messages(self.thread)
      self.assertEqual(len(messages), 1)
      run_id = messages[0]["run_id"]
      self.assertEqual(
        (await self.runtime.runs.get_run_snapshot(self.thread, run_id))["status"],
        "running",
      )
      owner = self.runtime.executions.get(self.thread, run_id)
      assert owner is not None and owner.task is not None
      self.assertFalse(owner.task.done())
      self.assertEqual(self.graph.calls, 0)
      await asyncio.wait_for(self.runtime.lifecycle.shutdown(), 2)
    self.assertIsNone(self.runtime.executions.get(self.thread, run_id))
    self.assertTrue(owner.task.cancelled())
    self.assertEqual(
      (await self.runtime.runs.get_run_snapshot(self.thread, run_id))["status"],
      "running",
    )
