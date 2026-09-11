import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI, HTTPException, Request
from shikigen.run_manager import RunManager, RunStatus
from shikigen.stream import StreamManager

from app.persistence import ChatStore
from app.routes.run import (
  ChatRequest,
  get_run_messages,
  stream_chat,
  stream_run_events,
)
from app.server import app as server_app


class RegisteredRoutesTests(unittest.IsolatedAsyncioTestCase):
  async def test_server_registers_thread_and_run_routes(self) -> None:
    store = SimpleNamespace(
      list_threads=AsyncMock(return_value=[]),
      create_thread=AsyncMock(),
      thread_exists=AsyncMock(return_value=False),
      list_messages_by_run=AsyncMock(return_value=None),
    )
    runtime = SimpleNamespace(chat_store=store)
    transport = httpx.ASGITransport(app=server_app)
    with patch.object(server_app.state, "runtime", runtime, create=True):
      async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
      ) as client:
        response = await client.get("/api/threads")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])
        response = await client.post("/api/threads")
        self.assertEqual(response.status_code, 200)
        store.create_thread.assert_awaited_once_with(response.json()["thread_id"])

        for path, detail in (
          ("/api/threads/missing/messages", "Thread not found"),
          ("/api/threads/missing/runs/missing/messages", "Run not found"),
        ):
          response = await client.get(path)
          self.assertEqual(response.status_code, 404)
          self.assertEqual(response.json(), {"detail": detail})

        response = await client.post(
          "/api/threads/missing/stream", json={"message": "hello"}
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"detail": "Thread not found"})


class RunMessagesEndpointTests(unittest.IsolatedAsyncioTestCase):
  async def asyncSetUp(self) -> None:
    self.temp_dir = tempfile.TemporaryDirectory()
    self.store = await ChatStore.open(Path(self.temp_dir.name) / "shikigen.db")
    self.app = FastAPI()
    self.app.state.runtime = SimpleNamespace(chat_store=self.store)
    self.request = Request({"type": "http", "app": self.app})

  async def asyncTearDown(self) -> None:
    await self.store.close()
    self.temp_dir.cleanup()

  async def test_returns_only_messages_from_the_requested_run(self) -> None:
    await self.store.create_thread("thread-1")
    await self.store.create_run("run-1", "thread-1")
    await self.store.append_event(
      thread_id="thread-1",
      run_id="run-1",
      event_type="human_message",
      category="message",
      content={"type": "human", "content": "hello"},
    )

    response = await get_run_messages("thread-1", "run-1", self.request)

    data = response["data"]
    assert isinstance(data, list)
    self.assertEqual(data[0]["content"]["content"], "hello")

  async def test_returns_not_found_for_a_run_from_another_thread(self) -> None:
    await self.store.create_thread("thread-1")
    await self.store.create_thread("thread-2")
    await self.store.create_run("run-1", "thread-1")

    with self.assertRaises(HTTPException) as caught:
      await get_run_messages("thread-2", "run-1", self.request)

    self.assertEqual(caught.exception.status_code, 404)


class StreamChatTests(unittest.IsolatedAsyncioTestCase):
  async def test_run_survives_disconnect_and_cleans_up_after_persistence(
    self,
  ) -> None:
    for cancel_consumer in (False, True):
      with self.subTest(cancel_consumer=cancel_consumer):
        manager = RunManager(StreamManager())
        record = manager.create("thread-1")
        finish = asyncio.Event()
        persist = asyncio.Event()
        finished = asyncio.Event()
        received = asyncio.Event()

        async def produce(record, finish, finished, persist) -> None:
          record.start()
          record.stream.publish("metadata", {"run_id": record.run_id})
          await finish.wait()
          record.finish(RunStatus.COMPLETED)
          finished.set()
          await persist.wait()

        iterator = stream_run_events(record, manager)

        async def consume(iterator, received) -> None:
          async for _ in iterator:
            received.set()

        record.task = asyncio.create_task(produce(record, finish, finished, persist))
        try:
          if cancel_consumer:
            consumer = asyncio.create_task(consume(iterator, received))
            await asyncio.wait_for(received.wait(), timeout=1)
            consumer.cancel()
            with self.assertRaises(asyncio.CancelledError):
              await consumer
          else:
            await anext(iterator)
            await iterator.aclose()

          self.assertFalse(record.abort_event.is_set())
          self.assertFalse(record.task.done())
          self.assertIs(manager.get_active_by_thread("thread-1"), record)
          self.assertEqual(len(record.stream._subscribers), 0)
          finish.set()
          await asyncio.wait_for(finished.wait(), timeout=1)
          self.assertIs(manager.get(record.run_id), record)
          persist.set()
          await record.task
          self.assertIsNone(manager.get(record.run_id))
          self.assertEqual(record.status, RunStatus.COMPLETED)
        finally:
          await manager.shutdown()

  async def test_closing_chat_response_keeps_run_active(self) -> None:
    manager = RunManager(StreamManager())
    store = SimpleNamespace(
      thread_exists=AsyncMock(return_value=True),
      create_run=AsyncMock(),
      start_run=AsyncMock(),
    )
    app = FastAPI()
    app.state.runtime = SimpleNamespace(chat_store=store, run_manager=manager)
    request = Request({"type": "http", "app": app})

    async def produce(_runtime, record, _message, _tracker) -> None:
      record.start()
      record.stream.publish("metadata", {"run_id": record.run_id})
      await asyncio.Event().wait()

    with patch("app.routes.run.run_and_persist_status", side_effect=produce):
      response = await stream_chat(
        "thread-1",
        ChatRequest(message="hello"),
        request,
      )
      try:
        await anext(response.body_iterator)
        await response.body_iterator.aclose()
        record = manager.get_active_by_thread("thread-1")
        self.assertIsNotNone(record)
        self.assertFalse(record.abort_event.is_set())
      finally:
        await manager.shutdown()

  async def test_busy_thread_returns_conflict(self) -> None:
    manager = RunManager(StreamManager())
    record = manager.create("thread-1")
    store = SimpleNamespace(
      thread_exists=AsyncMock(return_value=True), create_run=AsyncMock()
    )
    app = FastAPI()
    app.state.runtime = SimpleNamespace(chat_store=store, run_manager=manager)
    app.post("/api/threads/{thread_id}/stream")(stream_chat)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
      for running in (False, True):
        if running:
          record.start()
        response = await client.post(
          "/api/threads/thread-1/stream", json={"message": "hello"}
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json(), {"detail": "Thread is busy with another run"})
    store.create_run.assert_not_awaited()
    self.assertIs(manager.get(record.run_id), record)
    self.assertFalse(record.abort_event.is_set())

  async def test_terminal_events_have_matching_names(self) -> None:
    for terminal_status in (RunStatus.COMPLETED, RunStatus.CANCELLED):
      with self.subTest(status=terminal_status):
        manager = RunManager(StreamManager())
        record = manager.create("thread-1")
        record.start()
        record.finish(terminal_status)
        events = [json.loads(line) async for line in stream_run_events(record, manager)]
        self.assertEqual(events[-1]["event"], f"run.{terminal_status.value}")
        self.assertEqual(events[-1]["data"], {"status": terminal_status.value})

  async def test_serializes_complete_events_as_json_lines(self) -> None:
    manager = RunManager(StreamManager())
    record = manager.create("thread-1")
    record.stream.publish("metadata", {"run_id": record.run_id})
    record.stream.publish("message", {"text": "你", "done": False})
    record.stream.publish("message", {"text": "", "done": True})
    record.stream.publish(
      "tool_call",
      {"name": "search", "input": {}, "output": {}},
    )
    record.stream.close()

    lines = [line async for line in stream_run_events(record, manager)]
    events = [json.loads(line) for line in lines]

    self.assertEqual(
      events,
      [
        {
          "id": "0",
          "event": "metadata",
          "data": {"run_id": record.run_id},
        },
        {
          "id": "1",
          "event": "message.delta",
          "data": {"delta": "你"},
          "output_index": 0,
        },
        {
          "id": "2",
          "event": "message.completed",
          "data": {},
          "output_index": 0,
        },
        {
          "id": "3",
          "event": "tool_call.completed",
          "data": {"name": "search", "input": {}, "output": {}},
          "output_index": 1,
        },
      ],
    )
    self.assertTrue(all(line.endswith("\n") for line in lines))
