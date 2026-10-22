"""真实本地资源经公开工具 API 的测试生命周期。"""

import asyncio
import json
import os
import tempfile
import unittest
from contextlib import suppress
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

import httpx
from shikigen.app_config import load_app_config
from shikigen.persistence import ChatStore
from shikigen.runtime.composition import assemble_runtime

from app.server import create_app
from tests.fixtures.mcp_http_server import McpHttpServer


class ToolTestLifecycleApiTests(unittest.IsolatedAsyncioTestCase):
  async def asyncSetUp(self):
    directory = tempfile.TemporaryDirectory()
    self.addCleanup(directory.cleanup)
    self.path = Path(directory.name) / "config.json"
    self.path.write_text('{"model": {}, "mcp": {}}', encoding="utf-8")
    store = await ChatStore.open(Path(directory.name) / "test.db")
    self.addAsyncCleanup(store.close)
    self.runtime = assemble_runtime(
      config=load_app_config(self.path), agent=None, chat_store=store
    )
    self.addAsyncCleanup(self.runtime.lifecycle.shutdown)
    app = create_app(runtime=self.runtime)
    lifespan = app.router.lifespan_context(app)
    await lifespan.__aenter__()
    self.addAsyncCleanup(lifespan.__aexit__, None, None, None)
    self.client = httpx.AsyncClient(
      transport=httpx.ASGITransport(app=app), base_url="http://test"
    )
    self.addAsyncCleanup(self.client.aclose)

  async def observation(self, test_id):
    response = await self.client.get("/api/tools/tests/" + test_id)
    self.assertEqual(response.status_code, 200, response.text)
    snapshot = response.json()["data"]
    self.assertNotIn("phase", snapshot)
    return snapshot

  async def wait_finished(self, test_id):
    async with asyncio.timeout(10):
      while (observed := await self.observation(test_id))["status"] == "running":
        await asyncio.sleep(0.01)
    return observed

  async def python_blocker(self):
    started, closed = asyncio.Event(), asyncio.Event()
    process = {}

    async def connected(reader, writer):
      try:
        process.update(json.loads(await reader.readline()))
        started.set()
        with suppress(ConnectionError):
          await reader.read()
      finally:
        writer.close()
        with suppress(ConnectionError):
          await writer.wait_closed()
        closed.set()

    server = await asyncio.start_server(connected, "127.0.0.1", 0)

    async def close_server():
      await self.runtime.lifecycle.shutdown()
      server.close()
      await server.wait_closed()

    self.addAsyncCleanup(close_server)
    port = server.sockets[0].getsockname()[1]
    source = (
      "import socket, json, os\n"
      "def main():\n"
      f"  with socket.create_connection(('127.0.0.1', {port})) as channel:\n"
      "    print('before stop', flush=True)\n"
      "    identity = {'pid': os.getpid(), 'cwd': os.getcwd()}\n"
      "    channel.sendall((json.dumps(identity) + '\\n').encode())\n"
      "    channel.recv(1)\n"
    )
    return source, started, closed, process

  def assert_process_stopped(self, pid):
    if os.name == "nt":
      import ctypes
      from ctypes import wintypes

      kernel = ctypes.WinDLL("kernel32", use_last_error=True)
      kernel.OpenProcess.restype = wintypes.HANDLE
      handle = kernel.OpenProcess(0x1000, False, pid)
      if handle:
        try:
          code = wintypes.DWORD()
          self.assertTrue(kernel.GetExitCodeProcess(handle, ctypes.byref(code)))
          self.assertNotEqual(code.value, 259)
        finally:
          kernel.CloseHandle(handle)
    else:
      with self.assertRaises(ProcessLookupError):
        os.kill(pid, 0)

  async def http_service(self, handler):
    writers = set()

    async def connected(reader, writer):
      writers.add(writer)
      try:
        headers = await reader.readuntil(b"\r\n\r\n")
        await handler(reader, writer, headers)
      except (ConnectionError, asyncio.IncompleteReadError):
        pass
      finally:
        writer.close()
        with suppress(ConnectionError):
          await writer.wait_closed()
        writers.discard(writer)

    server = await asyncio.start_server(connected, "127.0.0.1", 0)

    async def close_server():
      for writer in tuple(writers):
        writer.close()
      server.close()
      await server.wait_closed()

    self.addAsyncCleanup(close_server)
    return f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}/"

  async def test_cancel_draft_waits_for_python_cleanup_and_is_idempotent(self):
    source, started, closed, process = await self.python_blocker()
    before = self.path.read_bytes()
    response = await self.client.post(
      "/api/tools/tests",
      json={
        "definition": {
          "kind": "python",
          "display_name": "阻塞草稿",
          "name": "blocked",
          "source": source,
          "enabled": False,
        },
        "inputs": {},
      },
    )
    self.assertEqual(response.status_code, 202, response.text)
    test_id = response.json()["data"]["test_id"]
    await asyncio.wait_for(started.wait(), 5)
    self.assertEqual((await self.observation(test_id))["status"], "running")
    cancel_request = asyncio.create_task(
      self.client.post(f"/api/tools/tests/{test_id}/cancel")
    )
    async with asyncio.timeout(5):
      while not (await self.observation(test_id))["cancel_requested"]:
        await asyncio.sleep(0.01)
    # 已明确发出取消，断开观察请求不能再打断后台清理。
    cancel_request.cancel()
    await asyncio.gather(cancel_request, return_exceptions=True)
    cancelled = await self.client.post(f"/api/tools/tests/{test_id}/cancel")
    self.assertEqual(cancelled.status_code, 200, cancelled.text)
    observed = cancelled.json()["data"]
    self.assertEqual(observed["status"], "cancelled", observed)
    self.assertEqual(observed["result"]["data_available"], False)
    self.assertIn("before stop", observed["result"]["details"]["stdout"])
    self.assertIsInstance(observed["result"]["details"]["exit_code"], int)
    await asyncio.wait_for(closed.wait(), 2)
    self.assert_process_stopped(process["pid"])
    self.assertFalse(Path(process["cwd"]).exists())
    self.assertEqual(await self.observation(test_id), observed)
    repeated = await self.client.post(f"/api/tools/tests/{test_id}/cancel")
    self.assertEqual(repeated.json()["data"], observed)
    self.assertEqual(self.path.read_bytes(), before)
    self.assertEqual((await self.client.get("/api/tools")).json()["data"], [])
    self.assertEqual(
      (await self.client.post("/api/tools/tests/missing/cancel")).status_code, 404
    )

  async def test_http_cancel_and_timeout_close_incomplete_response_without_data(self):
    for action in ("cancel", "timeout"):
      with self.subTest(action=action):
        started, closed = asyncio.Event(), asyncio.Event()
        calls = []

        async def blocked(
          reader, writer, headers, calls=calls, started=started, closed=closed
        ):
          calls.append(headers)
          writer.write(
            b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
            b'Content-Length: 100\r\n\r\n{"partial":'
          )
          await writer.drain()
          started.set()
          try:
            await reader.read()
          finally:
            closed.set()

        url = await self.http_service(blocked)
        created = await self.client.post(
          "/api/tools",
          json={
            "kind": "http",
            "display_name": action,
            "name": action,
            "url": url,
            "timeout_seconds": 1 if action == "timeout" else 30,
            "enabled": False,
          },
        )
        tool_id = created.json()["data"]["id"]
        executed = await self.client.post(
          f"/api/tools/{tool_id}/execute", json={"inputs": {}}
        )
        self.assertEqual(executed.json()["data"]["error"]["code"], "disabled")
        self.assertEqual(calls, [])
        response = await self.client.post(
          f"/api/tools/{tool_id}/tests", json={"inputs": {}}
        )
        self.assertEqual(response.status_code, 202, response.text)
        test_id = response.json()["data"]["test_id"]
        await asyncio.wait_for(started.wait(), 5)
        if action == "cancel":
          observed = (
            await self.client.post(f"/api/tools/tests/{test_id}/cancel")
          ).json()["data"]
        else:
          observed = await self.wait_finished(test_id)
        result = observed["result"]
        self.assertEqual(
          observed["status"], "cancelled" if action == "cancel" else "timeout", observed
        )
        self.assertFalse(result["data_available"])
        self.assertEqual(result["data"], None)
        if action == "timeout":
          self.assertEqual(result["details"]["status_code"], 200)
        await asyncio.wait_for(closed.wait(), 2)
        self.assertEqual(len(calls), 1)
        self.assertEqual(await self.observation(test_id), observed)

  async def test_results_and_observed_inputs_hide_known_auth_values(self):
    secret = "sample-private-token"

    async def echo(reader, writer, headers):
      body = json.dumps(
        {
          "nested": [secret, "Bearer " + secret],
          secret: "kept",
          "query": ["first-private-key", "second-private-key"],
        }
      ).encode()
      writer.write(
        b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
        + f"X-Echo: {secret}\r\nContent-Length: {len(body)}\r\n\r\n".encode()
        + body
      )
      await writer.drain()

    url = await self.http_service(echo)
    response = await self.client.post(
      "/api/tools/tests",
      json={
        "definition": {
          "kind": "http",
          "display_name": "回显",
          "name": "echo",
          "url": url + "?api_key=first-private-key&api_key=second-private-key",
          "auth": [{"id": "bearer", "kind": "bearer", "value": "Bearer " + secret}],
          "input_schema": {
            "type": "object",
            "properties": {"body": {"type": "string"}},
          },
        },
        "inputs": {"body": secret},
      },
    )
    self.assertEqual(response.status_code, 202, response.text)
    self.assertNotIn(secret, response.text)
    observed = await self.wait_finished(response.json()["data"]["test_id"])
    self.assertEqual(observed["status"], "success", observed)
    self.assertTrue(observed["result"]["data_available"])
    self.assertNotIn(secret, json.dumps(observed))
    self.assertNotIn("first-private-key", json.dumps(observed))
    self.assertNotIn("second-private-key", json.dumps(observed))
    self.assertEqual(observed["inputs"], {"body": "[REDACTED]"})
    self.assertIn("kept", json.dumps(observed["result"]["data"]))

  async def import_mcp_tool(self, transport, **settings):
    created = await self.client.post(
      "/api/mcp/connections",
      json={
        "display_name": "生命周期服务",
        "transport": transport,
        **settings,
      },
    )
    self.assertEqual(created.status_code, 201, created.text)
    connection_id = created.json()["data"]["id"]
    base = f"/api/mcp/connections/{connection_id}"
    discovered = (await self.client.post(base + "/discover")).json()["data"]
    self.assertEqual(discovered["status"], "success", discovered)
    remote_name = "slow" if transport == "streamable_http" else "search"
    imported = await self.client.post(
      base + "/imports",
      json={
        "discovery_id": discovered["discovery_id"],
        "tools": [{"remote_name": remote_name, "name": "lifecycle_" + transport}],
      },
    )
    self.assertEqual(imported.status_code, 200, imported.text)
    return imported.json()["data"][0]["id"]

  async def test_cancel_stdio_test_reaps_its_process_and_closes_transport(self):
    import sys

    started, closed = asyncio.Event(), asyncio.Event()
    process = {}

    async def signal(reader, writer, headers):
      target = headers.decode().split(" ")[1]
      process["pid"] = int(parse_qs(urlsplit(target).query)["pid"][0])
      writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 1\r\n\r\n")
      await writer.drain()
      started.set()
      try:
        await reader.read()
      finally:
        closed.set()

    url = await self.http_service(signal)
    tool_id = await self.import_mcp_tool(
      "stdio",
      command=sys.executable,
      args=[str(Path(__file__).parent / "fixtures/mcp_stdio_server.py")],
      env={"MCP_FIXTURE_SIGNAL_URL": url, "MCP_FIXTURE_SIGNAL_PHASE": "tools/call"},
    )
    response = await self.client.post(
      f"/api/tools/{tool_id}/tests", json={"inputs": {"query": "block"}}
    )
    test_id = response.json()["data"]["test_id"]
    await asyncio.wait_for(started.wait(), 5)
    cancelled = await self.client.post(f"/api/tools/tests/{test_id}/cancel")
    self.assertEqual(cancelled.status_code, 200, cancelled.text)
    result = cancelled.json()["data"]["result"]
    self.assertEqual(result["status"], "cancelled", result)
    self.assertFalse(result["data_available"])
    await asyncio.wait_for(closed.wait(), 3)
    self.assert_process_stopped(process["pid"])
    self.assertEqual(result["details"]["transport"], "stdio")

  async def test_cancel_remote_mcp_test_releases_owned_session_and_never_retries_call(
    self,
  ):
    server = McpHttpServer()
    self.addCleanup(server.close)
    tool_id = await self.import_mcp_tool("streamable_http", url=server.url)
    response = await self.client.post(
      f"/api/tools/{tool_id}/tests", json={"inputs": {"query": "block"}}
    )
    test_id = response.json()["data"]["test_id"]
    self.assertTrue(await asyncio.to_thread(server.slow_started.wait, 5))
    observed = (await self.client.post(f"/api/tools/tests/{test_id}/cancel")).json()[
      "data"
    ]
    self.assertEqual(observed["status"], "cancelled", observed)
    self.assertFalse(observed["result"]["data_available"])
    self.assertEqual(server.sessions, set())
    self.assertEqual(server.calls, 1)
    self.assertEqual(await self.observation(test_id), observed)
    self.assertTrue(any(request["method"] == "DELETE" for request in server.requests))

  async def test_python_timeout_and_backend_shutdown_both_reap_owned_resources(self):
    for action in ("timeout", "shutdown"):
      with self.subTest(action=action):
        source, started, closed, process = await self.python_blocker()
        response = await self.client.post(
          "/api/tools/tests",
          json={
            "definition": {
              "kind": "python",
              "display_name": action,
              "name": action,
              "source": source,
              "timeout_seconds": 1 if action == "timeout" else 30,
            },
            "inputs": {},
          },
        )
        self.assertEqual(response.status_code, 202, response.text)
        test_id = response.json()["data"]["test_id"]
        await asyncio.wait_for(started.wait(), 5)
        if action == "shutdown":
          await self.runtime.lifecycle.shutdown()
        observed = await self.wait_finished(test_id)
        self.assertEqual(
          observed["status"],
          "timeout" if action == "timeout" else "cancelled",
          observed,
        )
        self.assertFalse(observed["result"]["data_available"])
        await asyncio.wait_for(closed.wait(), 2)
        self.assert_process_stopped(process["pid"])
        self.assertFalse(Path(process["cwd"]).exists())

  async def test_tool_initialization_budget_is_separate_from_connection_inspection(
    self,
  ):
    import sys

    signals = asyncio.Queue()

    async def signal(reader, writer, headers):
      target = headers.decode().split(" ")[1]
      pid = int(parse_qs(urlsplit(target).query)["pid"][0])
      writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 1\r\n\r\n")
      await writer.drain()
      await signals.put((pid, writer))
      await reader.read()

    url = await self.http_service(signal)
    tool_id = await self.import_mcp_tool(
      "stdio",
      command=sys.executable,
      args=[str(Path(__file__).parent / "fixtures/mcp_stdio_server.py")],
      test_timeout_seconds=5,
      discovery_timeout_seconds=5,
    )
    tool = (await self.client.get(f"/api/tools/{tool_id}")).json()["data"]
    base = f"/api/mcp/connections/{tool['connection_id']}"
    saved = (await self.client.get(base)).json()
    connection = {
      key: value
      for key, value in saved["data"].items()
      if key not in ("id", "created_at", "updated_at")
    }
    connection["env"] = {
      "MCP_FIXTURE_SIGNAL_URL": url,
      "MCP_FIXTURE_SIGNAL_PHASE": "initialize",
    }
    updated = await self.client.put(
      base, json={"definition": connection, "version": saved["version"]}
    )
    self.assertEqual(updated.status_code, 204, updated.text)
    response = await self.client.post(
      "/api/tools/tests",
      json={
        "tool_id": tool_id,
        "definition": {
          key: (1 if key == "timeout_seconds" else value)
          for key, value in tool.items()
          if key not in ("id", "created_at", "updated_at")
        },
        "inputs": {"query": "never-called"},
      },
    )
    self.assertEqual(response.status_code, 202, response.text)
    pid, _ = await asyncio.wait_for(signals.get(), 5)
    observed = await self.wait_finished(response.json()["data"]["test_id"])
    self.assertEqual(observed["status"], "timeout", observed)
    self.assertFalse(observed["result"]["data_available"])
    self.assertGreaterEqual(observed["result"]["duration_ms"], 950)
    self.assert_process_stopped(pid)
    inspected = asyncio.create_task(self.client.post(base + "/test"))
    pid, writer = await asyncio.wait_for(signals.get(), 5)
    # 超过工具的 1 秒预算仍在等待，因为连接检测独立使用 5 秒预算。
    with self.assertRaises(TimeoutError):
      await asyncio.wait_for(asyncio.shield(inspected), 1.1)
    writer.write(b"1")
    await writer.drain()
    inspection = (await asyncio.wait_for(inspected, 5)).json()["data"]
    self.assertEqual(inspection["status"], "success", inspection)
    self.assert_process_stopped(pid)

  async def test_start_returns_server_identity_for_query_and_cancellation(self):
    connections = asyncio.Queue()
    calls = []

    async def blocked(reader, writer, headers):
      closed = asyncio.Event()
      calls.append(headers)
      connections.put_nowait(closed)
      try:
        await reader.read()
      finally:
        closed.set()

    url = await self.http_service(blocked)
    definition = {
      "kind": "http",
      "name": "identity",
      "display_name": "测试身份",
      "url": url,
    }
    unknown_id = str(uuid4())
    cancelled = await self.client.post(f"/api/tools/tests/{unknown_id}/cancel")
    self.assertEqual(cancelled.status_code, 404, cancelled.text)
    self.assertEqual(
      (await self.client.get(f"/api/tools/tests/{unknown_id}")).status_code, 404
    )
    # 查询路径仍匹配该 URL，但已经没有登记用的 POST 方法。
    self.assertEqual(
      (await self.client.post("/api/tools/tests/reservations")).status_code, 405
    )
    supplied_id = await self.client.post(
      "/api/tools/tests",
      json={"definition": definition, "inputs": {}, "test_id": unknown_id},
    )
    self.assertEqual(supplied_id.status_code, 422, supplied_id.text)
    self.assertEqual(calls, [])

    identities = []
    for _ in range(2):
      response = await self.client.post(
        "/api/tools/tests", json={"definition": definition, "inputs": {}}
      )
      self.assertEqual(response.status_code, 202, response.text)
      snapshot = response.json()["data"]
      test_id = snapshot["test_id"]
      self.assertEqual(str(UUID(test_id)), test_id)
      self.assertEqual(snapshot["status"], "running")
      self.assertIsNone(snapshot["result"])
      self.assertNotIn("phase", snapshot)
      identities.append(test_id)
      closed = await asyncio.wait_for(connections.get(), 5)
      self.assertEqual((await self.observation(test_id))["status"], "running")
      variant = test_id.upper().replace("-", "")
      cancelled = await asyncio.wait_for(
        self.client.post(f"/api/tools/tests/{variant}/cancel"), 3
      )
      observed = cancelled.json()["data"]
      self.assertEqual(observed["status"], "cancelled", observed)
      self.assertEqual(observed["test_id"], test_id)
      await asyncio.wait_for(closed.wait(), 2)
      repeated = await self.client.post(f"/api/tools/tests/{test_id}/cancel")
      self.assertEqual(repeated.json()["data"], observed)
    self.assertNotEqual(*identities)
    self.assertEqual(len(calls), 2)

  async def test_active_capacity_and_completed_execution_reclamation(self):
    connections = asyncio.Queue()
    release = asyncio.Event()
    self.addCleanup(release.set)

    async def respond(reader, writer, headers):
      connections.put_nowait(None)
      if headers.split(b" ")[1] == b"/first":
        await release.wait()
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 4\r\n\r\nnull")
        await writer.drain()
      else:
        await reader.read()

    url = await self.http_service(respond)
    for _ in range(100):
      unknown = await self.client.post(f"/api/tools/tests/{uuid4()}/cancel")
      self.assertEqual(unknown.status_code, 404, unknown.text)
    identities = []
    for index in range(100):
      response = await self.client.post(
        "/api/tools/tests",
        json={
          "definition": {
            "kind": "http",
            "name": "capacity",
            "display_name": "容量测试",
            "url": url + ("first" if index == 0 else str(index)),
            "timeout_seconds": 300,
          },
          "inputs": {},
        },
      )
      self.assertEqual(response.status_code, 202, response.text)
      identities.append(response.json()["data"]["test_id"])
      await asyncio.wait_for(connections.get(), 5)
    payload = {
      "definition": {
        "kind": "http",
        "name": "overflow",
        "display_name": "容量不足",
        "url": url,
      },
      "inputs": {},
    }
    full = await self.client.post("/api/tools/tests", json=payload)
    self.assertEqual(full.status_code, 503, full.text)
    self.assertTrue(connections.empty())

    release.set()
    finished = await self.wait_finished(identities[0])
    self.assertEqual(finished["status"], "success", finished)
    fresh = await self.client.post("/api/tools/tests", json=payload)
    self.assertEqual(fresh.status_code, 202, fresh.text)
    await asyncio.wait_for(connections.get(), 5)
    self.assertEqual(
      (await self.client.get(f"/api/tools/tests/{identities[0]}")).status_code, 404
    )
    for test_id in identities[1:]:
      self.assertEqual((await self.observation(test_id))["status"], "running")
    await self.runtime.lifecycle.shutdown()

  async def test_shutdown_cancels_all_running_tests(self):
    connections = asyncio.Queue()

    async def blocked(reader, writer, headers):
      closed = asyncio.Event()
      connections.put_nowait(closed)
      try:
        await reader.read()
      finally:
        closed.set()

    url = await self.http_service(blocked)
    identities = []
    closed_connections = []
    for name in ("first", "second"):
      started = await self.client.post(
        "/api/tools/tests",
        json={
          "definition": {
            "kind": "http",
            "name": name,
            "display_name": name,
            "url": url,
          },
          "inputs": {},
        },
      )
      self.assertEqual(started.status_code, 202, started.text)
      identities.append(started.json()["data"]["test_id"])
      closed_connections.append(await asyncio.wait_for(connections.get(), 5))

    await self.runtime.lifecycle.shutdown()
    for closed in closed_connections:
      await asyncio.wait_for(closed.wait(), 2)
    for test_id in identities:
      observed = await self.observation(test_id)
      self.assertEqual(observed["status"], "cancelled", observed)
      self.assertTrue(observed["cancel_requested"])
      self.assertFalse(observed["result"]["data_available"])
      self.assertNotIn("task", observed)


if __name__ == "__main__":
  unittest.main()
