"""MCP 管理公开 API 与可控本地 stdio 服务，无模型或公网。"""

import asyncio
import ctypes
import json
import os
import sys
import tempfile
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import httpx
from shikigen.app_config import load_app_config
from shikigen.persistence import ChatStore
from shikigen.runtime.composition import assemble_runtime

from app.server import create_app


class McpToolApiTests(unittest.IsolatedAsyncioTestCase):
  async def asyncSetUp(self):
    directory = tempfile.TemporaryDirectory()
    self.addCleanup(directory.cleanup)
    self.path = Path(directory.name) / "config.json"
    self.path.write_text(json.dumps({"model": {}, "mcp": {}}), encoding="utf-8")
    store = await ChatStore.open(Path(directory.name) / "test.db")
    self.addAsyncCleanup(store.close)
    runtime = assemble_runtime(
      config=load_app_config(self.path), agent=None, chat_store=store
    )
    self.runtime = runtime
    self.addAsyncCleanup(runtime.lifecycle.shutdown)
    app = create_app(runtime=runtime)
    context = app.router.lifespan_context(app)
    await context.__aenter__()
    self.addAsyncCleanup(context.__aexit__, None, None, None)
    self.client = httpx.AsyncClient(
      transport=httpx.ASGITransport(app=app), base_url="http://test"
    )
    self.addAsyncCleanup(self.client.aclose)

  async def create_connection(self, **overrides):
    response = await self.client.post(
      "/api/mcp/connections",
      json={"display_name": "本地服务", "command": sys.executable, **overrides},
    )
    self.assertEqual(response.status_code, 201, response.text)
    return (
      await self.client.get("/api/mcp/connections/" + response.json()["data"]["id"])
    ).json()

  async def test_save_unreachable_stdio_connection_and_read_independent_collection(
    self,
  ):
    schema = await self.client.get("/api/mcp/schema/stdio")
    self.assertEqual(schema.status_code, 200, schema.text)
    self.assertIn("command", schema.json()["data"]["properties"])
    saved = await self.create_connection(
      command="missing-mcp-executable",
      args=["--stdio"],
      env={"MODE": "$LITERAL"},
      cwd="missing-directory",
      test_timeout_seconds=3,
      discovery_timeout_seconds=4,
    )
    connection = saved["data"]
    self.assertEqual(connection["env"], {"MODE": "$LITERAL"})
    self.assertEqual(connection["transport"], "stdio")
    self.assertEqual(connection["discovery_timeout_seconds"], 4)
    listed = (await self.client.get("/api/mcp/connections")).json()
    self.assertEqual(listed["data"], [connection])
    self.assertEqual((await self.client.get("/api/tools")).json()["data"], [])
    definition = {
      k: v for k, v in connection.items() if k not in ("id", "created_at", "updated_at")
    }
    updated = await self.client.put(
      f"/api/mcp/connections/{connection['id']}",
      json={
        "definition": {**definition, "display_name": "改名"},
        "version": saved["version"],
      },
    )
    self.assertEqual(updated.status_code, 204, updated.text)
    reread = (await self.client.get(f"/api/mcp/connections/{connection['id']}")).json()
    self.assertEqual(reread["data"]["id"], connection["id"])
    self.assertEqual(reread["data"]["created_at"], connection["created_at"])
    self.assertEqual(reread["data"]["display_name"], "改名")
    self.assertEqual(json.loads(self.path.read_text())["mcp"], {})

  async def discover(self, saved):
    response = await self.client.post(
      f"/api/mcp/connections/{saved['data']['id']}/discover"
    )
    self.assertEqual(response.status_code, 200, response.text)
    self.assertEqual(response.json()["data"]["status"], "success", response.text)
    return response.json()["data"]

  async def test_connect_discover_select_and_call_preserves_source_and_raw_result(self):
    saved = await self.create_connection(
      args=[str(Path(__file__).parent / "fixtures/mcp_stdio_server.py")],
      env={"MODE": "literal"},
      cwd=str(self.path.parent),
    )
    connection_id = saved["data"]["id"]
    connected = await self.client.post(f"/api/mcp/connections/{connection_id}/test")
    self.assertEqual(connected.status_code, 200, connected.text)
    self.assertEqual(connected.json()["data"]["status"], "success", connected.text)
    preview = await self.discover(saved)
    self.assertEqual(len(preview["tools"]), 7)
    self.assertTrue(all(tool["x-discovery-calls"] == 0 for tool in preview["tools"]))
    self.assertEqual((await self.client.get("/api/tools")).json()["data"], [])
    response = await self.client.post(
      f"/api/mcp/connections/{connection_id}/imports",
      json={
        "discovery_id": preview["discovery_id"],
        "tools": [{"remote_name": "search", "name": "fixture_search"}],
      },
    )
    self.assertEqual(response.status_code, 200, response.text)
    imported = response.json()["data"]
    self.assertEqual(len(imported), 1)
    tool_id = imported[0]["id"]
    tool = (await self.client.get("/api/tools/" + tool_id)).json()["data"]
    self.assertEqual(tool["connection_id"], connection_id)
    self.assertEqual(tool["source_tool"], preview["tools"][0])
    self.assertEqual(tool["input_schema"], preview["tools"][0]["inputSchema"])
    self.assertEqual(len((await self.client.get("/api/tools")).json()["data"]), 1)
    result = (
      await self.client.post(
        f"/api/tools/{tool_id}/execute", json={"inputs": {"query": "hello"}}
      )
    ).json()["data"]
    self.assertEqual(result["status"], "success", result)
    self.assertEqual(result["data"]["arguments"], {"query": "hello"})
    self.assertEqual(result["data"]["calls"], 1)
    self.assertEqual(result["data"]["mode"], "literal")
    self.assertEqual(Path(result["data"]["cwd"]), self.path.parent)
    self.assertEqual(result["details"]["raw_result"]["vendor"], {"complete": True})
    self.assertEqual(len(result["details"]["raw_result"]["content"]), 2)
    self.assertEqual(result["details"]["raw_result"]["_meta"], {"source": "fixture"})

  async def test_batch_import_is_atomic_and_sources_cannot_be_forged(self):
    saved = await self.create_connection(
      args=[str(Path(__file__).parent / "fixtures/mcp_stdio_server.py")]
    )
    connection_id = saved["data"]["id"]
    preview = await self.discover(saved)
    before = (await self.client.get("/api/tools")).json()
    for selections in (
      [
        {"remote_name": "search", "name": "search"},
        {"remote_name": "unsupported", "name": "bad"},
      ],
      [
        {"remote_name": "search", "name": "same"},
        {"remote_name": "blocks", "name": "same"},
      ],
      [{"remote_name": "search", "name": "add"}],
      [{"remote_name": "forged", "name": "fake"}],
    ):
      with self.subTest(selections=selections):
        response = await self.client.post(
          f"/api/mcp/connections/{connection_id}/imports",
          json={
            "discovery_id": preview["discovery_id"],
            "tools": selections,
          },
        )
        self.assertIn(response.status_code, (409, 422), response.text)
        self.assertEqual((await self.client.get("/api/tools")).json(), before)
    forged = await self.client.post(
      "/api/tools",
      json={
        "kind": "mcp",
        "name": "forged",
        "display_name": "fake",
        "connection_id": connection_id,
        "remote_name": "search",
      },
    )
    self.assertEqual(forged.status_code, 422, forged.text)
    self.assertEqual(forged.json()["detail"]["code"], "read_only")

  async def import_selected(self, saved, names):
    preview = await self.discover(saved)
    response = await self.client.post(
      f"/api/mcp/connections/{saved['data']['id']}/imports",
      json={
        "discovery_id": preview["discovery_id"],
        "tools": [{"remote_name": name, "name": "fixture_" + name} for name in names],
      },
    )
    self.assertEqual(response.status_code, 200, response.text)
    return response.json()["data"]

  async def execute(self, tool_id, inputs):
    response = await self.client.post(
      f"/api/tools/{tool_id}/execute", json={"inputs": inputs}
    )
    self.assertEqual(response.status_code, 200, response.text)
    return response.json()["data"]

  async def test_raw_blocks_business_error_output_error_and_size_limit(self):
    saved = await self.create_connection(
      args=[str(Path(__file__).parent / "fixtures/mcp_stdio_server.py")]
    )
    imported = await self.import_selected(
      saved, ["blocks", "fail", "invalid_output", "huge"]
    )
    by_name = {item["remote_name"]: item["id"] for item in imported}
    blocks = await self.execute(by_name["blocks"], {"query": "hello"})
    self.assertEqual(blocks["status"], "success", blocks)
    self.assertEqual(blocks["data"], blocks["details"]["raw_result"]["content"])
    self.assertIsNone(blocks["details"]["raw_result"]["structuredContent"])
    for name, code in (
      ("fail", "mcp_tool_error"),
      ("invalid_output", "mcp_output_validation"),
      ("huge", "output_limit"),
    ):
      with self.subTest(name=name):
        result = await self.execute(by_name[name], {"query": "hello"})
        self.assertEqual(result["status"], "error", result)
        self.assertEqual(result["error"]["code"], code)
        if name != "huge":
          self.assertEqual(
            result["details"]["raw_result"]["vendor"], {"complete": True}
          )
        else:
          self.assertGreater(result["details"]["received_bytes"], 1024 * 1024)
          self.assertNotIn("raw_result", result["details"])

  async def test_fresh_sessions_reimport_identity_local_permissions_and_strict_inputs(
    self,
  ):
    saved = await self.create_connection(
      args=[str(Path(__file__).parent / "fixtures/mcp_stdio_server.py")]
    )
    imported = await self.import_selected(saved, ["search"])
    tool_id = imported[0]["id"]
    reread = await self.import_selected(saved, ["search", "blocks"])
    self.assertEqual(
      reread[0], {"id": tool_id, "remote_name": "search", "existing": True}
    )
    self.assertEqual(len((await self.client.get("/api/tools")).json()["data"]), 2)
    first = await self.execute(tool_id, {"query": "one"})
    second = await self.execute(tool_id, {"query": "two"})
    self.assertEqual(first["data"]["calls"], 1)
    self.assertEqual(second["data"]["calls"], 1)
    self.assertNotEqual(first["data"]["pid"], second["data"]["pid"])
    self.assert_process_stopped(first["data"]["pid"])
    self.assert_process_stopped(second["data"]["pid"])
    invalid = await self.execute(tool_id, {"query": 3})
    self.assertEqual(invalid["error"]["code"], "input_validation")
    detail = (await self.client.get("/api/tools/" + tool_id)).json()
    for changes in (
      {"connection_id": "another"},
      {"remote_name": "blocks"},
      {"input_schema": {"type": "object"}},
      {"source_tool": {}},
      {"discovery_update": True},
    ):
      response = await self.client.put(
        "/api/tools/" + tool_id,
        json={
          "definition": {"display_name": "x", "name": "x", **changes},
          "version": detail["version"],
        },
      )
      self.assertEqual(response.status_code, 422, response.text)
    editable = {
      "kind": "mcp",
      "display_name": "本地名",
      "name": "local_search",
      "description": "本地说明",
      "enabled": False,
      "timeout_seconds": 2,
    }
    response = await self.client.put(
      "/api/tools/" + tool_id,
      json={"definition": editable, "version": detail["version"]},
    )
    self.assertEqual(response.status_code, 204, response.text)
    local = (await self.client.get("/api/tools/" + tool_id)).json()
    self.assertEqual(local["data"]["source_tool"], detail["data"]["source_tool"])
    self.assertEqual(
      (await self.execute(tool_id, {"query": "disabled"}))["error"]["code"], "disabled"
    )
    draft = await self.client.post(
      "/api/tools/tests",
      json={"tool_id": tool_id, "definition": editable, "inputs": {"query": "draft"}},
    )
    self.assertEqual(draft.status_code, 202, draft.text)
    for _ in range(100):
      tested = (
        await self.client.get("/api/tools/tests/" + draft.json()["data"]["test_id"])
      ).json()["data"]
      if tested["status"] != "running":
        break
      await asyncio.sleep(0.02)
    self.assertEqual(tested["status"], "success", tested)
    self.assertEqual((await self.client.get("/api/tools/" + tool_id)).json(), local)

  async def test_connection_diagnostics_and_separate_budgets(self):
    missing = await self.create_connection(command="missing-fixture-stdio-command")
    unavailable = await self.client.post(
      f"/api/mcp/connections/{missing['data']['id']}/test"
    )
    self.assertEqual(unavailable.json()["data"]["status"], "error", unavailable.text)
    pid_file = self.path.parent / "initializing.pid"
    slow = await self.create_connection(
      args=[str(Path(__file__).parent / "fixtures/mcp_stdio_server.py")],
      env={"MCP_INITIALIZE_DELAY": "5", "MCP_FIXTURE_PID_FILE": str(pid_file)},
      test_timeout_seconds=1,
      discovery_timeout_seconds=1,
    )
    for action in ("test", "discover"):
      response = await self.client.post(
        f"/api/mcp/connections/{slow['data']['id']}/{action}"
      )
      self.assertEqual(response.json()["data"]["status"], "timeout", response.text)
      self.assertNotIn("discovery_id", response.json()["data"])
      self.assert_process_stopped(int(pid_file.read_text()))

  def assert_process_stopped(self, pid):
    if os.name == "nt":
      kernel = ctypes.WinDLL("kernel32", use_last_error=True)
      kernel.OpenProcess.restype = ctypes.c_void_p
      kernel.GetExitCodeProcess.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_ulong),
      ]
      kernel.CloseHandle.argtypes = [ctypes.c_void_p]
      handle = kernel.OpenProcess(0x1000, False, pid)
      if handle:
        try:
          code = ctypes.c_ulong()
          self.assertTrue(kernel.GetExitCodeProcess(handle, ctypes.byref(code)))
          self.assertNotEqual(code.value, 259, f"stdio process {pid} is still running")
        finally:
          kernel.CloseHandle(handle)
    else:
      with self.assertRaises(ProcessLookupError):
        os.kill(pid, 0)

  async def test_timeout_and_shutdown_release_owned_stdio_process(self):
    pid_file = self.path.parent / "mcp-process.pid"
    saved = await self.create_connection(
      args=[str(Path(__file__).parent / "fixtures/mcp_stdio_server.py")],
      env={"MCP_FIXTURE_PID_FILE": str(pid_file)},
    )
    imported = await self.import_selected(saved, ["slow"])
    tool_id = imported[0]["id"]
    detail = (await self.client.get("/api/tools/" + tool_id)).json()
    updated = await self.client.put(
      "/api/tools/" + tool_id,
      json={
        "definition": {
          "kind": "mcp",
          "name": "slow",
          "display_name": "slow",
          "timeout_seconds": 1,
        },
        "version": detail["version"],
      },
    )
    self.assertEqual(updated.status_code, 204, updated.text)
    result = await self.execute(tool_id, {"query": "timeout"})
    self.assertEqual(result["status"], "timeout", result)
    self.assert_process_stopped(int(pid_file.read_text()))
    pid_file.unlink()
    response = await self.client.post(
      f"/api/tools/{tool_id}/tests", json={"inputs": {"query": "cancel"}}
    )
    self.assertEqual(response.status_code, 202, response.text)
    for _ in range(100):
      if pid_file.exists():
        break
      await asyncio.sleep(0.02)
    self.assertTrue(pid_file.exists())
    await self.runtime.lifecycle.shutdown()
    observation = (
      await self.client.get("/api/tools/tests/" + response.json()["data"]["test_id"])
    ).json()["data"]
    self.assertEqual(observation["status"], "cancelled", observation)
    self.assert_process_stopped(int(pid_file.read_text()))

  async def test_paginated_discovery_stale_preview_and_protocol_failure(self):
    source = {"name": "protocol", "inputSchema": {"type": "object", "properties": {}}}
    saved = await self.create_connection(
      args=[str(Path(__file__).parent / "fixtures/mcp_stdio_server.py")],
      env={
        "MCP_FIXTURE_PAGINATE": "1",
        "MCP_FIXTURE_TOOLS": json.dumps([source, {**source, "name": "search"}]),
      },
    )
    preview = await self.discover(saved)
    self.assertEqual(
      [tool["name"] for tool in preview["tools"]], ["protocol", "search"]
    )
    await self.client.post(
      "/api/tools",
      json={"display_name": "HTTP", "name": "http", "url": "http://localhost/"},
    )
    stale = await self.client.post(
      f"/api/mcp/connections/{saved['data']['id']}/imports",
      json={
        "discovery_id": preview["discovery_id"],
        "tools": [{"remote_name": "protocol", "name": "fixture_protocol"}],
      },
    )
    self.assertEqual(stale.status_code, 409, stale.text)
    self.assertEqual(stale.json()["detail"]["code"], "version_conflict")
    imported = await self.import_selected(saved, ["protocol"])
    result = await self.execute(imported[0]["id"], {})
    self.assertEqual(result["status"], "error", result)
    self.assertEqual(result["error"]["code"], "mcp_protocol")
    self.assertIn("fixture protocol failure", result["error"]["message"])

  async def test_live_output_schema_does_not_fetch_external_references(self):
    requests = []

    class Handler(BaseHTTPRequestHandler):
      def do_GET(self):
        requests.append(self.path)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"type":"object"}')

      def log_message(self, format, *args):
        pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    Thread(target=server.serve_forever, daemon=True).start()
    self.addCleanup(server.server_close)
    self.addCleanup(server.shutdown)
    source = {"name": "search", "inputSchema": {"type": "object", "properties": {}}}
    saved = await self.create_connection(
      args=[str(Path(__file__).parent / "fixtures/mcp_stdio_server.py")],
      env={"MCP_FIXTURE_TOOLS": json.dumps([source])},
    )
    imported = await self.import_selected(saved, ["search"])
    source["outputSchema"] = {
      "type": "object",
      "allOf": [{"$ref": f"http://127.0.0.1:{server.server_port}/schema"}],
    }
    current = (
      await self.client.get(f"/api/mcp/connections/{saved['data']['id']}")
    ).json()
    definition = {
      key: value
      for key, value in current["data"].items()
      if key not in ("id", "created_at", "updated_at")
    }
    definition["env"] = {"MCP_FIXTURE_TOOLS": json.dumps([source])}
    updated = await self.client.put(
      f"/api/mcp/connections/{saved['data']['id']}",
      json={"definition": definition, "version": current["version"]},
    )
    self.assertEqual(updated.status_code, 204, updated.text)
    result = await self.execute(imported[0]["id"], {})
    self.assertEqual(result["status"], "error", result)
    self.assertEqual(result["error"]["code"], "mcp_output_validation")
    self.assertEqual(requests, [])
    self.assertIn("raw_result", result["details"])
