"""通过公开 API 验证远程 MCP；所有 HTTP 流量留在本机。"""

import asyncio
import json
import tempfile
import time
import unittest
from pathlib import Path

import httpx
from shikigen.app_config import load_app_config
from shikigen.persistence import ChatStore
from shikigen.runtime.composition import assemble_runtime

from app.server import create_app
from tests.fixtures.mcp_http_server import McpHttpServer


class McpHttpApiTests(unittest.IsolatedAsyncioTestCase):
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
      json={
        "display_name": "远程服务",
        "transport": "streamable_http",
        "url": "http://127.0.0.1:1/mcp",
        **overrides,
      },
    )
    self.assertEqual(response.status_code, 201, response.text)
    return (
      await self.client.get("/api/mcp/connections/" + response.json()["data"]["id"])
    ).json()

  async def test_http_rediscovery_updates_selected_source_and_cascade_deletes(self):
    server = McpHttpServer()
    self.addCleanup(server.close)
    saved = await self.create_connection(url=server.url)
    connection_id = saved["data"]["id"]
    ids = await self.import_tools(connection_id, ["search", "blocks"])
    before = (await self.client.get("/api/tools")).json()
    source = {
      "name": "search",
      "inputSchema": {"type": "object", "properties": {"term": {"type": "string"}}},
    }
    server.tools_override = [source]
    base = f"/api/mcp/connections/{connection_id}"
    preview = (await self.client.post(base + "/discover")).json()["data"]
    self.assertEqual(
      {item["remote_name"]: item["status"] for item in preview["changes"]},
      {"search": "changed", "blocks": "missing"},
    )
    self.assertEqual((await self.client.get("/api/tools")).json(), before)
    self.assertEqual(server.calls, 0)
    applied = await self.client.post(
      base + "/imports",
      json={
        "discovery_id": preview["discovery_id"],
        "tools": [{"remote_name": "search", "name": "http_search"}],
      },
    )
    self.assertEqual(applied.status_code, 200, applied.text)
    updated = (await self.client.get("/api/tools/" + ids["search"])).json()["data"]
    self.assertEqual(updated["input_schema"], source["inputSchema"])
    self.assertEqual(updated["source_tool"], source)
    blocks = (await self.client.get("/api/tools/" + ids["blocks"])).json()["data"]
    self.assertEqual(
      blocks, next(tool for tool in before["data"] if tool["id"] == ids["blocks"])
    )
    version = (await self.client.get(base)).json()["version"]
    deleted = await self.client.request("DELETE", base, json={"version": version})
    self.assertEqual(deleted.status_code, 204, deleted.text)
    self.assertEqual((await self.client.get("/api/tools")).json()["data"], [])

  async def test_offline_http_connection_has_own_schema_and_uses_same_collection(self):
    saved = await self.create_connection(
      headers={"X-Workspace": "$LITERAL"},
      test_timeout_seconds=2,
      discovery_timeout_seconds=3,
    )
    schema = await self.client.get("/api/mcp/schema/streamable_http")
    self.assertEqual(schema.status_code, 200, schema.text)
    self.assertIn("url", schema.json()["data"]["properties"])
    self.assertNotIn("command", schema.json()["data"]["properties"])
    connection = saved["data"]
    self.assertEqual(connection["transport"], "streamable_http")
    self.assertEqual(connection["headers"], {"X-Workspace": "$LITERAL"})
    self.assertEqual(connection["test_timeout_seconds"], 2)
    self.assertEqual(connection["discovery_timeout_seconds"], 3)
    listed = (await self.client.get("/api/mcp/connections")).json()
    self.assertEqual(listed["data"], [connection])
    self.assertEqual((await self.client.get("/api/tools")).json()["data"], [])
    self.assertEqual(json.loads(self.path.read_text())["mcp"], {})

  async def test_http_connection_rejects_invalid_url_headers_and_budget(self):
    for changes in (
      {"url": "file:///tmp/server"},
      {"url": "http://user:password@localhost/mcp"},
      {"url": "http://localhost/mcp#fragment"},
      {"headers": {"Authorization": "a\r\nb"}},
      {"headers": {"Host": "another-host"}},
      {"headers": {"X-Test": "one", "x-test": "two"}},
      {"test_timeout_seconds": 0},
    ):
      with self.subTest(changes=changes):
        response = await self.client.post(
          "/api/mcp/connections",
          json={
            "display_name": "无效配置",
            "transport": "streamable_http",
            "url": "http://localhost/mcp",
            **changes,
          },
        )
        self.assertEqual(response.status_code, 422, response.text)
    self.assertEqual((await self.client.get("/api/mcp/connections")).json()["data"], [])

  async def test_remote_initialize_discover_import_and_call_json_and_sse(self):
    server = McpHttpServer()
    self.addCleanup(server.close)
    server.authorization = "Bearer fixture-secret"
    for endpoint in ("/mcp", "/sse"):
      with self.subTest(endpoint=endpoint):
        saved = await self.create_connection(
          url=server.url + endpoint,
          headers={"Authorization": server.authorization},
        )
        connection_id = saved["data"]["id"]
        base = f"/api/mcp/connections/{connection_id}"
        tested = (await self.client.post(base + "/test")).json()["data"]
        self.assertEqual(tested["status"], "success", tested)
        preview = (await self.client.post(base + "/discover")).json()["data"]
        self.assertEqual(preview["status"], "success", preview)
        self.assertEqual(server.calls, 0)
        self.assertEqual(server.sessions, set())
        imported = await self.client.post(
          base + "/imports",
          json={
            "discovery_id": preview["discovery_id"],
            "tools": [{"remote_name": "search", "name": "search" + endpoint[1:]}],
          },
        )
        self.assertEqual(imported.status_code, 200, imported.text)
        tool_id = imported.json()["data"][0]["id"]
        tool = (await self.client.get("/api/tools/" + tool_id)).json()["data"]
        self.assertEqual(tool["kind"], "mcp")
        self.assertEqual(tool["connection_id"], connection_id)
        self.assertEqual(tool["input_schema"], preview["tools"][0]["inputSchema"])
        session_ids = []
        for query in ("one", "two"):
          executed = (
            await self.client.post(
              f"/api/tools/{tool_id}/execute", json={"inputs": {"query": query}}
            )
          ).json()["data"]
          self.assertEqual(executed["status"], "success", executed)
          self.assertEqual(executed["data"]["arguments"], {"query": query})
          self.assertEqual(len(executed["details"]["raw_result"]["content"]), 2)
          self.assertEqual(
            executed["details"]["raw_result"]["_meta"], {"source": "http-fixture"}
          )
          self.assertEqual(
            executed["details"]["raw_result"]["vendor"], {"complete": True}
          )
          session_ids.append(executed["data"]["session"])
          self.assertEqual(server.sessions, set())
        self.assertNotEqual(*session_ids)
        server.calls = 0

  async def test_authentication_transport_and_protocol_errors_are_distinct(self):
    server = McpHttpServer()
    self.addCleanup(server.close)
    server.authorization = "Bearer required"
    saved = await self.create_connection(url=server.url + "/mcp")
    base = f"/api/mcp/connections/{saved['data']['id']}"
    unauthorized = (await self.client.post(base + "/test")).json()["data"]
    self.assertEqual(unauthorized["error"]["code"], "mcp_authentication", unauthorized)
    server.authorization = None
    unavailable = await self.create_connection(url=server.url + "/unavailable")
    observed = (
      await self.client.post(f"/api/mcp/connections/{unavailable['data']['id']}/test")
    ).json()["data"]
    self.assertEqual(observed["error"]["code"], "mcp_transport", observed)
    offline = await self.create_connection()
    observed = (
      await self.client.post(f"/api/mcp/connections/{offline['data']['id']}/test")
    ).json()["data"]
    self.assertEqual(observed["error"]["code"], "mcp_transport", observed)

  async def import_tools(self, connection_id, names):
    base = f"/api/mcp/connections/{connection_id}"
    discovered = (await self.client.post(base + "/discover")).json()["data"]
    self.assertEqual(discovered["status"], "success", discovered)
    imported = await self.client.post(
      base + "/imports",
      json={
        "discovery_id": discovered["discovery_id"],
        "tools": [{"remote_name": name, "name": "http_" + name} for name in names],
      },
    )
    self.assertEqual(imported.status_code, 200, imported.text)
    return {item["remote_name"]: item["id"] for item in imported.json()["data"]}

  async def execute(self, tool_id, query="hello"):
    response = await self.client.post(
      f"/api/tools/{tool_id}/execute", json={"inputs": {"query": query}}
    )
    self.assertEqual(response.status_code, 200, response.text)
    return response.json()["data"]

  async def test_remote_raw_blocks_business_protocol_and_output_limit(self):
    server = McpHttpServer()
    self.addCleanup(server.close)
    saved = await self.create_connection(url=server.url + "/mcp")
    tools = await self.import_tools(
      saved["data"]["id"], ["blocks", "fail", "protocol", "huge"]
    )
    blocks = await self.execute(tools["blocks"])
    self.assertEqual(blocks["status"], "success", blocks)
    self.assertEqual(blocks["data"], blocks["details"]["raw_result"]["content"])
    for name, code in (
      ("fail", "mcp_tool_error"),
      ("protocol", "mcp_protocol"),
      ("huge", "output_limit"),
    ):
      with self.subTest(name=name):
        result = await self.execute(tools[name])
        self.assertEqual(result["status"], "error", result)
        self.assertEqual(result["error"]["code"], code)
        self.assertEqual(result["details"]["transport"], "streamable_http")
        self.assertEqual(server.sessions, set())

  async def test_remote_inspection_reports_protocol_and_initialization_timeout(self):
    server = McpHttpServer()
    self.addCleanup(server.close)
    for endpoint, status, code in (
      ("/protocol", "error", "mcp_protocol"),
      ("/malformed", "error", "mcp_protocol"),
      ("/html", "error", "mcp_protocol"),
      ("/slow", "timeout", "timeout"),
    ):
      saved = await self.create_connection(
        url=server.url + endpoint,
        test_timeout_seconds=1,
        discovery_timeout_seconds=1,
      )
      for operation in ("test", "discover"):
        with self.subTest(endpoint=endpoint, operation=operation):
          observation = (
            await self.client.post(
              f"/api/mcp/connections/{saved['data']['id']}/{operation}"
            )
          ).json()["data"]
          self.assertEqual(observation["status"], status, observation)
          self.assertEqual(observation["error"]["code"], code)
          self.assertNotIn("discovery_id", observation)

  async def test_remote_timeout_and_shutdown_close_owned_mcp_sessions(self):
    server = McpHttpServer()
    self.addCleanup(server.close)
    saved = await self.create_connection(url=server.url + "/mcp")
    tools = await self.import_tools(saved["data"]["id"], ["slow"])
    tool_id = tools["slow"]
    detail = (await self.client.get("/api/tools/" + tool_id)).json()
    definition = {
      key: value
      for key, value in detail["data"].items()
      if key not in ("id", "created_at", "updated_at")
    }
    updated = await self.client.put(
      "/api/tools/" + tool_id,
      json={
        "definition": {**definition, "timeout_seconds": 1},
        "version": detail["version"],
      },
    )
    self.assertEqual(updated.status_code, 204, updated.text)
    server.slow_delete = True
    timed_out = await self.execute(tool_id)
    self.assertEqual(timed_out["status"], "timeout", timed_out)
    self.assertLess(timed_out["duration_ms"], 2500)
    self.assertEqual(server.sessions, set())
    server.slow_started.clear()
    started = await self.client.post(
      f"/api/tools/{tool_id}/tests", json={"inputs": {"query": "cancel"}}
    )
    self.assertEqual(started.status_code, 202, started.text)
    self.assertTrue(await asyncio.to_thread(server.slow_started.wait, 5))
    test_id = started.json()["data"]["test_id"]
    shutdown_started = time.monotonic()
    await self.runtime.lifecycle.shutdown()
    self.assertLess(time.monotonic() - shutdown_started, 1.5)
    observed = (await self.client.get(f"/api/tools/tests/{test_id}")).json()["data"]
    self.assertEqual(observed["status"], "cancelled", observed)
    self.assertEqual(server.sessions, set())

  async def test_remote_sse_ends_without_a_result_reports_transport_error(self):
    server = McpHttpServer()
    self.addCleanup(server.close)
    saved = await self.create_connection(
      url=server.url + "/sse-eof", discovery_timeout_seconds=2
    )
    observed = (
      await self.client.post(f"/api/mcp/connections/{saved['data']['id']}/discover")
    ).json()["data"]
    self.assertEqual(observed["status"], "error", observed)
    self.assertEqual(observed["error"]["code"], "mcp_transport", observed)
    self.assertNotIn("discovery_id", observed)
    self.assertEqual(server.sessions, set())

  async def test_remote_sse_with_event_id_resumes_without_repeating_business(self):
    server = McpHttpServer()
    self.addCleanup(server.close)
    saved = await self.create_connection(url=server.url + "/resume")
    observed = (
      await self.client.post(f"/api/mcp/connections/{saved['data']['id']}/discover")
    ).json()["data"]
    self.assertEqual(observed["status"], "success", observed)
    self.assertEqual(observed["tools"], [])
    self.assertTrue(
      any(
        request["method"] == "GET" and request["last_event_id"] == "recover"
        for request in server.requests
      )
    )
    self.assertEqual(server.calls, 0)
    self.assertEqual(server.sessions, set())

  async def test_remote_connection_edit_keeps_source_identity_and_direct_headers(self):
    server = McpHttpServer()
    self.addCleanup(server.close)
    saved = await self.create_connection(
      url=server.url + "/mcp", headers={"Authorization": "Bearer first"}
    )
    connection_id = saved["data"]["id"]
    tools = await self.import_tools(connection_id, ["search"])
    base = f"/api/mcp/connections/{connection_id}"
    detail = (await self.client.get(base)).json()
    definition = {
      key: value
      for key, value in detail["data"].items()
      if key not in ("id", "created_at", "updated_at")
    }
    for headers in ({"Authorization": "Bearer replaced"}, {}):
      updated = await self.client.put(
        base,
        json={
          "definition": {**definition, "url": server.url + "/sse", "headers": headers},
          "version": detail["version"],
        },
      )
      self.assertEqual(updated.status_code, 204, updated.text)
      detail = (await self.client.get(base)).json()
      self.assertEqual(detail["data"]["headers"], headers)
      self.assertEqual(detail["data"]["created_at"], saved["data"]["created_at"])
      before = (await self.client.get("/api/tools/" + tools["search"])).json()["data"]
      reimported = await self.import_tools(connection_id, ["search"])
      self.assertEqual(reimported, tools)
      after = (await self.client.get("/api/tools/" + tools["search"])).json()["data"]
      self.assertEqual(
        {
          key: value
          for key, value in after.items()
          if key not in ("source_tool", "updated_at")
        },
        {
          key: value
          for key, value in before.items()
          if key not in ("source_tool", "updated_at")
        },
      )
      self.assertEqual(after["source_tool"]["x-business-calls"], server.calls)
      result = await self.execute(tools["search"])
      self.assertEqual(result["status"], "success", result)
      call = next(
        request
        for request in reversed(server.requests)
        if request["message"] and request["message"]["method"] == "tools/call"
      )
      self.assertEqual(call["path"], "/sse")
      self.assertEqual(call["authorization"], headers.get("Authorization"))
