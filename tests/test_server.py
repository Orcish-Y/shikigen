import asyncio
import tempfile
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI, Request
from runtime_fixtures import deterministic_agent
from shikigen.app_config import AppConfig, McpConfig, ModelConfig
from shikigen.contracts.runs import StorageConflict
from shikigen.core.execution import RunExecution
from shikigen.persistence import ChatStore
from shikigen.runtime.composition import assemble_runtime, open_runtime
from shikigen.runtime.runs import RunTransitions
from sse_fixtures import parse_sse, parse_sse_frames
from starlette.requests import ClientDisconnect
from test_loop import BlockingAgent, MessageAgent

from app.routes.run import (
  ChatRequest,
  ObservationResponse,
  stream_chat,
  stream_run_events,
)
from app.server import app as server_app


class LifespanTests(unittest.IsolatedAsyncioTestCase):
  async def test_lifespan_uses_shared_context_and_releases_it(self):
    runtime = SimpleNamespace(lifecycle=SimpleNamespace(shutdown=AsyncMock()))
    entered, exited = [], []

    @asynccontextmanager
    async def context():
      entered.append(True)
      try:
        yield runtime
      finally:
        await runtime.lifecycle.shutdown()
        exited.append(True)

    app = FastAPI()
    with patch("app.server.open_runtime", side_effect=context) as factory:
      async with server_app.router.lifespan_context(app):
        self.assertIs(app.state.runtime, runtime)
        self.assertEqual(entered, [True])
        self.assertEqual(exited, [])
        runtime.lifecycle.shutdown.assert_not_awaited()
      factory.assert_called_once_with()
    runtime.lifecycle.shutdown.assert_awaited_once()
    self.assertEqual(exited, [True])
    self.assertFalse(hasattr(app.state, "runtime"))


class ServerTests(unittest.IsolatedAsyncioTestCase):
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
    patcher = patch.object(server_app.state, "runtime", self.runtime, create=True)
    patcher.start()
    self.addCleanup(patcher.stop)
    self.client = httpx.AsyncClient(
      transport=httpx.ASGITransport(app=server_app), base_url="http://test"
    )
    self.addAsyncCleanup(self.client.aclose)

  async def test_registered_routes_creation_and_not_found(self):
    self.assertEqual((await self.client.get("/api/threads")).json(), [])
    with patch.object(
      self.runtime.threads, "create_thread", wraps=self.runtime.threads.create_thread
    ) as create:
      response = await self.client.post("/api/threads")
      self.assertEqual(response.status_code, 200)
      create.assert_awaited_once_with()
    threads = (await self.client.get("/api/threads")).json()
    self.assertEqual(threads[0]["id"], response.json()["thread_id"])
    for path, detail in (
      ("/api/threads/missing/messages", "Thread not found"),
      ("/api/threads/missing/runs/missing/messages", "Run not found"),
    ):
      result = await self.client.get(path)
      self.assertEqual(result.status_code, 404)
      self.assertEqual(result.json(), {"detail": detail})
    result = await self.client.post(
      "/api/threads/missing/stream", json={"message": "hello"}
    )
    self.assertEqual(result.status_code, 404)

  async def test_http_uses_shared_start_and_returns_matching_committed_terminal(self):
    thread = await self.runtime.threads.create_thread()
    with patch.object(
      self.runtime.runs, "start_run", wraps=self.runtime.runs.start_run
    ) as start:
      response = await self.client.post(
        f"/api/threads/{thread}/stream", json={"message": "hello"}
      )
      start.assert_awaited_once_with(thread, "hello")
    self.assertEqual(response.status_code, 200)
    self.assertIn("text/event-stream", response.headers["content-type"])
    events = parse_sse_frames(response.text)
    run_id = events[0]["data"]["run_id"]
    self.assertEqual(events[-1]["event"], "metadata")
    self.assertEqual(events[-1]["data"]["status"], "completed")
    self.assertEqual(
      (await self.runtime.runs.read_run(thread, run_id))["status"], "completed"
    )
    messages = await self.client.get(f"/api/threads/{thread}/runs/{run_id}/messages")
    self.assertEqual(messages.json()["data"][0]["content"]["content"], "hello")
    other = await self.runtime.threads.create_thread()
    self.assertEqual(
      (
        await self.client.get(f"/api/threads/{other}/runs/{run_id}/messages")
      ).status_code,
      404,
    )

  async def test_get_existing_stream_rebuilds_and_rejects_cursors(self):
    thread = await self.runtime.threads.create_thread()
    execution = await self.runtime.runs.start_run(thread, "hello")
    await self.runtime.runs.wait_run(execution)
    path = f"/api/threads/{thread}/runs/{execution.run_id}/stream"
    with patch.object(
      self.runtime.runs, "start_run", side_effect=AssertionError("read only")
    ):
      first = await self.client.get(path)
      second = await self.client.get(path)
    self.assertEqual(first.status_code, 200)
    self.assertEqual(first.text, second.text)
    frames = parse_sse_frames(first.text)
    self.assertEqual(frames[0]["data"]["status"], "completed")
    self.assertEqual(frames[-1]["data"]["payload"]["status"], "completed")
    for suffix, headers in (
      ("?cursor=1", {}),
      ("?after_seq=1", {}),
      ("", {"Last-Event-ID": "1"}),
    ):
      self.assertEqual(
        (await self.client.get(path + suffix, headers=headers)).status_code, 400
      )
    self.assertEqual(
      (await self.client.get(path.replace(thread, "missing"))).status_code, 404
    )

  async def test_running_without_local_execution_returns_retryable_503(self):
    from langchain_core.messages import HumanMessage

    thread = await self.runtime.threads.create_thread()
    await RunTransitions(self.store).create_run(
      thread_id=thread,
      run_id="orphan",
      entry_message=HumanMessage(id="h", content="hi"),
    )
    response = await self.client.get(f"/api/threads/{thread}/runs/orphan/stream")
    self.assertEqual(response.status_code, 503)
    self.assertEqual(response.headers["retry-after"], "1")
    self.assertEqual(
      (await self.runtime.runs.read_run(thread, "orphan"))["status"], "running"
    )

  async def test_get_response_send_failure_releases_unstarted_observation(self):
    thread = await self.runtime.threads.create_thread()
    self.runtime.runs.agent = BlockingAgent()
    execution = await self.runtime.runs.start_run(thread, "hello")
    observation = await self.runtime.runs.observe_run(thread, execution.run_id)
    response = ObservationResponse(observation)

    async def fail_send(message):
      raise OSError("disconnected before body")

    with self.assertRaises(ClientDisconnect):
      await response(
        {"type": "http", "asgi": {"spec_version": "2.4"}},
        AsyncMock(),
        fail_send,
      )
    self.assertEqual(len(execution.stream._subscribers), 0)
    self.assertFalse(execution.abort_event.is_set())

  async def test_busy_thread_returns_conflict(self):
    thread = await self.runtime.threads.create_thread()
    self.runtime.runs.agent = BlockingAgent()
    execution = await self.runtime.runs.start_run(thread, "first")
    response = await self.client.post(
      f"/api/threads/{thread}/stream", json={"message": "second"}
    )
    self.assertEqual(response.status_code, 409)
    self.assertEqual(response.json(), {"detail": "Thread is busy with another run"})
    self.assertFalse(execution.abort_event.is_set())

  async def test_storage_identity_conflicts_map_to_409(self):
    for service, operation, path, body in (
      (self.runtime.threads, "create_thread", "/api/threads", None),
      (self.runtime.runs, "start_run", "/api/threads/thread/stream", {"message": "hi"}),
    ):
      with self.subTest(operation=operation):
        with patch.object(
          service, operation, side_effect=StorageConflict("Persistent identity exists")
        ):
          response = await self.client.post(path, json=body)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json(), {"detail": "Persistent identity exists"})

  async def test_http_disconnect_leaves_execution_and_commit_running(self):
    for cancel_consumer in (False, True):
      with self.subTest(cancel_consumer=cancel_consumer):
        entered, release, received = asyncio.Event(), asyncio.Event(), asyncio.Event()
        original = self.runtime.runs._transitions.settle_execution

        async def settle(entered=entered, release=release, original=original, **kwargs):
          entered.set()
          await release.wait()
          return await original(**kwargs)

        with patch.object(
          self.runtime.runs._transitions, "settle_execution", side_effect=settle
        ):
          thread = await self.runtime.threads.create_thread()
          response = await stream_chat(
            thread,
            ChatRequest(message="hello"),
            Request({"type": "http", "app": server_app}),
          )
          iterator = response.body_iterator
          first = parse_sse(await anext(iterator))
          run_id = first["data"]["run_id"]
          execution = self.runtime.executions.get(thread, run_id)
          await asyncio.wait_for(entered.wait(), 2)
          if cancel_consumer:

            async def consume(received=received, iterator=iterator):
              received.set()
              async for _ in iterator:
                pass

            consumer = asyncio.create_task(consume())
            await received.wait()
            consumer.cancel()
            with self.assertRaises(asyncio.CancelledError):
              await consumer
          else:
            await iterator.aclose()
          self.assertFalse(execution.task.done())
          self.assertFalse(execution.abort_event.is_set())
          self.assertEqual(len(execution.stream._subscribers), 0)
          release.set()
          self.assertEqual(
            (await self.runtime.runs.wait_run(execution))["status"], "completed"
          )
          self.assertIsNone(self.runtime.executions.get(thread, run_id))

  async def test_storage_failure_has_no_success_terminal(self):
    thread = await self.runtime.threads.create_thread()
    with (
      patch.object(
        self.runtime.runs._transitions,
        "settle_execution",
        side_effect=OSError("disk failed"),
      ),
      self.assertLogs("shikigen.runtime.run_execution", level="ERROR"),
    ):
      response = await self.client.post(
        f"/api/threads/{thread}/stream", json={"message": "hello"}
      )
    events = parse_sse_frames(response.text)
    self.assertEqual(events[-1]["event"], "error")
    self.assertFalse(
      any(e["event"] in ("run.completed", "run.error", "run.cancelled") for e in events)
    )

  async def test_real_agent_through_http_uses_same_persistence_path(self):
    config = AppConfig(
      model=ModelConfig(),
      mcp=McpConfig(),
      database={"path": str(Path(self.directory.name) / "real.db")},
      checkpointer={"type": "memory"},
    )
    with patch(
      "shikigen.runtime.composition.create_lead_agent", new=deterministic_agent
    ):
      async with open_runtime(config) as runtime:
        with patch.object(server_app.state, "runtime", runtime):
          thread = (await self.client.post("/api/threads")).json()["thread_id"]
          response = await self.client.post(
            f"/api/threads/{thread}/stream", json={"message": "1+2"}
          )
          events = parse_sse_frames(response.text)
          self.assertEqual(events[-1]["data"]["status"], "completed")
          messages = (await self.client.get(f"/api/threads/{thread}/messages")).json()[
            "data"
          ]
          self.assertEqual(
            [m["content"]["type"] for m in messages], ["human", "ai", "tool", "ai"]
          )


class EncoderTests(unittest.IsolatedAsyncioTestCase):
  async def test_terminal_names_include_interrupted(self):
    for status in ("completed", "cancelled", "interrupted"):
      execution = RunExecution("run", "thread")
      execution.stream.publish("status", {"status": status})
      execution.stream.close()
      events = [parse_sse(line) async for line in stream_run_events(execution)]
      self.assertEqual(events[-1]["event"], "metadata")
      self.assertEqual(
        events[-1]["data"], {"thread_id": "thread", "run_id": "run", "status": status}
      )

  async def test_serializes_sse_and_omits_ephemeral_completion_events(self):
    execution = RunExecution("run", "thread")
    execution.stream.publish("metadata", {"run_id": "run"})
    execution.stream.publish(
      "message", {"text": "你\n好", "done": False, "message_id": "answer", "seq": 3}
    )
    execution.stream.publish("message", {"text": "", "done": True})
    execution.stream.publish("tool_call", {"name": "search", "input": {}, "output": {}})
    execution.stream.close()
    frames = [frame async for frame in stream_run_events(execution)]
    self.assertEqual(
      [parse_sse(frame) for frame in frames],
      [
        {
          "event": "metadata",
          "data": {"thread_id": "thread", "run_id": "run", "status": "running"},
        },
        {
          "event": "delta",
          "data": {
            "message_id": "answer",
            "seq": 3,
            "field": "content",
            "value": "你\n好",
          },
        },
      ],
    )
    self.assertTrue(all(frame.endswith("\n\n") for frame in frames))

  async def test_run_failure_is_lifecycle_fact_and_metadata_not_observation_error(self):
    execution = RunExecution("run", "thread")
    execution.stream.publish(
      "durable_event",
      {
        "id": 1,
        "thread_id": "thread",
        "run_id": "run",
        "seq": 1,
        "event_type": "run_error",
        "category": "lifecycle",
        "event_key": "settled:run",
        "content": {
          "status": "error",
          "message": "model failed",
          "error_code": "execution_failed",
        },
        "metadata": {},
        "created_at": "2026-09-18T00:00:00+00:00",
      },
    )
    execution.stream.publish("error", {"message": "model failed"})
    execution.stream.close()
    frames = [parse_sse(frame) async for frame in stream_run_events(execution)]
    self.assertEqual(
      [frame["event"] for frame in frames], ["metadata", "event", "metadata"]
    )
    self.assertEqual(frames[1]["data"]["event_type"], "status_changed")
    self.assertEqual(frames[1]["data"]["payload"]["status"], "error")
    self.assertEqual(frames[-1]["data"]["status"], "error")

  async def test_usage_is_metadata_and_null_artifact_survives_sse(self):
    execution = RunExecution("run", "thread")
    usage = {
      "total_input": 1,
      "total_output": 2,
      "total_tokens": 3,
      "calls": 1,
      "by_model": {},
    }
    execution.stream.publish("usage", usage)
    execution.stream.publish(
      "durable_event",
      {
        "id": 2,
        "thread_id": "thread",
        "run_id": "run",
        "seq": 2,
        "event_type": "tool_message",
        "category": "message",
        "event_key": "tool:call",
        "content": {
          "type": "tool",
          "message_id": "tool-result:call",
          "tool_call_id": "call",
          "content": "ok",
          "status": "success",
          "artifact": None,
        },
        "metadata": {},
        "created_at": "2026-09-18T00:00:00+00:00",
      },
    )
    execution.stream.close()
    frames = [parse_sse(frame) async for frame in stream_run_events(execution)]
    self.assertEqual(frames[1]["data"]["usage"], usage)
    self.assertEqual(frames[2]["event"], "event")
    self.assertIsNone(frames[2]["data"]["payload"]["artifact"])
    self.assertNotIn("name", frames[2]["data"]["payload"])
