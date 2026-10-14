import asyncio
import json
import os
import tempfile
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import httpx
from shikigen.app_config import load_app_config
from shikigen.contracts.tool_definitions import (
  HttpToolDefinition,
  McpToolDefinition,
  PythonToolDefinition,
)
from shikigen.persistence import ChatStore
from shikigen.runtime.composition import assemble_runtime

from app.server import create_app


class ToolLibraryApiTests(unittest.IsolatedAsyncioTestCase):
  async def asyncSetUp(self):
    self.directory = tempfile.TemporaryDirectory()
    self.addCleanup(self.directory.cleanup)
    self.path = Path(self.directory.name) / "loaded-config.json"
    self.original = {
      "model": {},
      "mcp": {},
      "workspace_root": ".",
      "database": {"path": "./relative.db"},
    }
    self.path.write_text(json.dumps(self.original), encoding="utf-8")
    self.store = await ChatStore.open(Path(self.directory.name) / "tests.db")
    self.addAsyncCleanup(self.store.close)
    runtime = assemble_runtime(
      config=load_app_config(self.path), agent=None, chat_store=self.store
    )
    self.app = create_app(runtime=runtime)
    context = self.app.router.lifespan_context(self.app)
    await context.__aenter__()
    self.addAsyncCleanup(context.__aexit__, None, None, None)
    self.client = httpx.AsyncClient(
      transport=httpx.ASGITransport(app=self.app), base_url="http://test"
    )
    self.addAsyncCleanup(self.client.aclose)
    self.addAsyncCleanup(runtime.lifecycle.shutdown)

  async def read_created_tool(self, response):
    self.assertEqual(response.status_code, 201, response.text)
    tool_id = response.json()["data"]["id"]
    loaded = await self.client.get(f"/api/tools/{tool_id}")
    self.assertEqual(loaded.status_code, 200, loaded.text)
    return loaded.json()

  async def test_create_and_reread_from_loaded_config_preserves_other_groups(self):
    environment = patch.dict(os.environ, {"TOOL_TEST_ENDPOINT": "https://example.test"})
    environment.start()
    self.addCleanup(environment.stop)
    self.original["model"] = {"base_url": "$TOOL_TEST_ENDPOINT"}
    self.original["mcp"] = {
      "servers": {
        "boot": {
          "transport": "stdio",
          "command": "relative-command",
          "args": ["./server.py"],
        }
      }
    }
    self.path.write_text(json.dumps(self.original), encoding="utf-8")
    response = await self.client.post(
      "/api/tools",
      json={
        "kind": "http",
        "display_name": "第一个工具",
        "name": "first_tool",
        "description": "$LITERAL",
        "url": "http://127.0.0.1/example",
      },
    )
    self.assertEqual(response.status_code, 201, response.text)
    saved = (await self.read_created_tool(response))["data"]
    self.assertTrue(saved["id"])
    self.assertTrue(saved["enabled"])
    self.assertEqual(saved["timeout_seconds"], 30)
    self.assertEqual(saved["input_schema"]["type"], "object")
    reread = await self.client.get(f"/api/tools/{saved['id']}")
    self.assertEqual(reread.json()["data"], saved)
    raw = json.loads(self.path.read_text(encoding="utf-8"))
    self.assertEqual(
      {k: v for k, v in raw.items() if k != "tool_library"}, self.original
    )
    reloaded = load_app_config(self.path)
    other_app = create_app(
      runtime=assemble_runtime(config=reloaded, agent=None, chat_store=self.store)
    )
    async with other_app.router.lifespan_context(other_app):
      async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=other_app), base_url="http://test"
      ) as client:
        listed = await client.get("/api/tools")
        self.assertEqual(listed.json()["data"], [saved])

  async def test_writes_return_id_or_empty_success_and_details_are_read_separately(
    self,
  ):
    payload = {
      "kind": "http",
      "display_name": "精简响应",
      "name": "write_response",
      "url": "http://localhost/",
    }
    created = await self.client.post("/api/tools", json=payload)
    self.assertEqual(created.status_code, 201, created.text)
    self.assertEqual(set(created.json()), {"data"})
    self.assertEqual(set(created.json()["data"]), {"id"})
    tool_id = created.json()["data"]["id"]
    saved = (await self.client.get(f"/api/tools/{tool_id}")).json()
    self.assertEqual(saved["data"]["display_name"], "精简响应")
    self.assertIsInstance(saved["version"], str)
    updated = await self.client.put(
      f"/api/tools/{tool_id}",
      json={
        "definition": {**payload, "display_name": "修改后"},
        "version": saved["version"],
      },
    )
    self.assertEqual(updated.status_code, 204, updated.text)
    self.assertEqual(updated.content, b"")
    reread = (await self.client.get(f"/api/tools/{tool_id}")).json()
    self.assertEqual(reread["data"]["display_name"], "修改后")
    self.assertNotEqual(reread["version"], saved["version"])
    deleted = await self.client.request(
      "DELETE", f"/api/tools/{tool_id}", json={"version": reread["version"]}
    )
    self.assertEqual(deleted.status_code, 204, deleted.text)
    self.assertEqual(deleted.content, b"")
    self.assertEqual((await self.client.get(f"/api/tools/{tool_id}")).status_code, 404)

  async def test_mixed_tool_library_roundtrips_concrete_definitions(self):
    saved = []
    variants = (
      (HttpToolDefinition, {"kind": "http", "url": "http://localhost/"}),
      (PythonToolDefinition, {"kind": "python", "code_path": "tools/example.py"}),
      (
        McpToolDefinition,
        {"kind": "mcp", "server_id": "local", "remote_name": "search"},
      ),
    )
    for _, fields in variants:
      with self.subTest(kind=fields["kind"]):
        created = await self.client.post(
          "/api/tools",
          json={"display_name": "工具", "name": f"tool_{fields['kind']}", **fields},
        )
        self.assertEqual(created.status_code, 201, created.text)
        tool = (await self.read_created_tool(created))["data"]
        saved.append(tool)
        for field, value in fields.items():
          self.assertEqual(tool[field], value)
        reread = await self.client.get(f"/api/tools/{tool['id']}")
        self.assertEqual(reread.json()["data"], tool)
    self.assertEqual(len({tool["name"] for tool in saved}), 3)
    self.assertEqual(
      [tool["name"] for tool in saved], ["tool_http", "tool_python", "tool_mcp"]
    )
    self.assertEqual((await self.client.get("/api/tools")).json()["data"], saved)

    config = load_app_config(self.path)
    for tool, (definition_type, _) in zip(
      config.tool_library.tools, variants, strict=True
    ):
      self.assertIsInstance(tool, definition_type)
    self.assertEqual(config.tool_library.model_dump(mode="json")["tools"], saved)
    reloaded = create_app(
      runtime=assemble_runtime(config=config, agent=None, chat_store=self.store)
    )
    async with reloaded.router.lifespan_context(reloaded):
      async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=reloaded), base_url="http://test"
      ) as client:
        self.assertEqual((await client.get("/api/tools")).json()["data"], saved)

    python = saved[1]
    edited = {
      key: value
      for key, value in python.items()
      if key not in ("id", "kind", "created_at", "updated_at")
    }
    edited["code_path"] = "tools/updated.py"
    version = (await self.client.get("/api/tools")).json()["version"]
    updated = await self.client.put(
      f"/api/tools/{python['id']}", json={"definition": edited, "version": version}
    )
    self.assertEqual(updated.status_code, 204, updated.text)
    updated_tool = (await self.client.get(f"/api/tools/{python['id']}")).json()["data"]
    self.assertEqual(updated_tool["kind"], "python")
    self.assertEqual(updated_tool["id"], python["id"])
    self.assertEqual(updated_tool["created_at"], python["created_at"])
    self.assertEqual(updated_tool["code_path"], "tools/updated.py")
    saved[1] = updated_tool
    raw = json.loads(self.path.read_text(encoding="utf-8"))
    self.assertEqual(raw["tool_library"]["tools"], saved)
    self.assertEqual(
      {k: v for k, v in raw.items() if k != "tool_library"}, self.original
    )

  async def test_discriminator_and_type_specific_fields_reject_invalid_definitions(
    self,
  ):
    before = self.path.read_bytes()
    for fields in (
      {"kind": "unknown", "url": "http://localhost/"},
      {"kind": None, "url": "http://localhost/"},
      {"kind": "http"},
      {"kind": "python"},
      {"kind": "python", "code_path": ""},
      {"kind": "python", "code_path": "tools/example.py", "url": "http://localhost/"},
      {"kind": "mcp", "url": "http://localhost/"},
      {"kind": "mcp", "server_id": "local", "remote_name": ""},
      {"kind": "mcp", "server_id": "local", "remote_name": 1},
    ):
      with self.subTest(fields=fields):
        response = await self.client.post(
          "/api/tools", json={"display_name": "无效定义", "name": "invalid", **fields}
        )
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(response.json()["detail"]["code"], "definition_invalid")
        self.assertEqual(self.path.read_bytes(), before)

  async def test_edit_cannot_change_tool_kind(self):
    created = await self.client.post(
      "/api/tools",
      json={
        "kind": "python",
        "display_name": "固定类型",
        "name": "fixed_kind",
        "code_path": "tools/example.py",
      },
    )
    self.assertEqual(created.status_code, 201, created.text)
    created_snapshot = await self.read_created_tool(created)
    tool = created_snapshot["data"]
    before = self.path.read_bytes()
    response = await self.client.put(
      f"/api/tools/{tool['id']}",
      json={
        "definition": {
          "kind": "mcp",
          "display_name": tool["display_name"],
          "name": tool["name"],
          "server_id": "local",
          "remote_name": "search",
        },
        "version": created_snapshot["version"],
      },
    )
    self.assertEqual(response.status_code, 422, response.text)
    self.assertEqual(response.json()["detail"]["code"], "read_only")
    self.assertEqual(self.path.read_bytes(), before)

  async def test_unregistered_tool_adapters_fail_explicitly_after_successful_save(self):
    for fields in (
      {"kind": "python", "code_path": "tools/example.py"},
      {"kind": "mcp", "server_id": "local", "remote_name": "search"},
    ):
      with self.subTest(kind=fields["kind"]):
        created = await self.client.post(
          "/api/tools",
          json={
            "display_name": "尚未接入执行",
            "name": f"tool_{fields['kind']}",
            **fields,
          },
        )
        self.assertEqual(created.status_code, 201, created.text)
        response = await self.client.post(
          f"/api/tools/{created.json()['data']['id']}/execute", json={"inputs": {}}
        )
        result = response.json()["data"]
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"]["code"], "unsupported_kind")
        self.assertIsNone(result["data"])

  async def test_saved_tool_test_observes_real_http_json_without_agent(self):
    class Handler(BaseHTTPRequestHandler):
      def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"values":[null,false,0,"",[],{}]}')

      def log_message(self, format, *args):
        pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    self.addCleanup(server.server_close)
    self.addCleanup(server.shutdown)
    saved = (
      await self.client.post(
        "/api/tools",
        json={
          "display_name": "真实 GET",
          "name": "real_get",
          "url": f"http://127.0.0.1:{server.server_port}/",
        },
      )
    ).json()["data"]
    started = await self.client.post(
      f"/api/tools/{saved['id']}/tests", json={"inputs": {}}
    )
    self.assertEqual(started.status_code, 202, started.text)
    snapshot = started.json()["data"]
    for _ in range(100):
      snapshot = (
        await self.client.get(f"/api/tools/tests/{snapshot['test_id']}")
      ).json()["data"]
      if snapshot["status"] != "running":
        break
      await asyncio.sleep(0.01)
    self.assertEqual(snapshot["status"], "success")
    result = snapshot["result"]
    self.assertEqual(result["data"], {"values": [None, False, 0, "", [], {}]})
    self.assertIsNone(result["error"])
    self.assertEqual(result["details"]["status_code"], 200)
    self.assertGreaterEqual(result["duration_ms"], 0)
    direct = await self.client.post(
      f"/api/tools/{saved['id']}/execute", json={"inputs": {}}
    )
    self.assertEqual(direct.json()["data"]["data"], result["data"])

  async def test_duplicate_display_names_and_call_name_conflicts(
    self,
  ):
    payload = {"display_name": "add", "name": "custom_add", "url": "http://localhost/"}
    first = await self.client.post("/api/tools", json=payload)
    first_saved = await self.read_created_tool(first)
    second = await self.client.post(
      "/api/tools", json={**payload, "name": "custom_add_2"}
    )
    self.assertEqual(first.status_code, 201)
    self.assertEqual(second.status_code, 201)
    second_saved = await self.read_created_tool(second)
    self.assertNotEqual(first_saved["data"]["name"], "add")
    self.assertNotEqual(first_saved["data"]["name"], second_saved["data"]["name"])
    before = self.path.read_bytes()
    for name in ("add", first_saved["data"]["name"]):
      response = await self.client.post("/api/tools", json={**payload, "name": name})
      self.assertEqual(response.status_code, 409)
      self.assertEqual(response.json()["detail"]["code"], "name_conflict")
    self.assertEqual(self.path.read_bytes(), before)
    saved = first_saved["data"]
    edited = {
      key: value
      for key, value in saved.items()
      if key not in ("id", "created_at", "updated_at")
    }
    edited["display_name"] = "中文改名"
    response = await self.client.put(
      f"/api/tools/{saved['id']}",
      json={
        "definition": edited,
        "version": second_saved["version"],
      },
    )
    self.assertEqual(response.status_code, 204)
    updated_saved = (await self.client.get(f"/api/tools/{saved['id']}")).json()["data"]
    self.assertEqual(updated_saved["id"], saved["id"])
    self.assertEqual(updated_saved["created_at"], saved["created_at"])
    stale = await self.client.put(
      f"/api/tools/{saved['id']}",
      json={
        "definition": edited,
        "version": first_saved["version"],
      },
    )
    self.assertEqual(stale.status_code, 409)

  async def test_name_validation_and_save_share_format_rules(self):
    before = self.path.read_bytes()
    for name in (
      "",
      "1tool",
      "中文",
      "has space",
      "has-dash",
      "a/b",
      "valid\n",
      "x" * 65,
    ):
      with self.subTest(name=name):
        checked = await self.client.get(
          "/api/tools/validate-name", params={"name": name}
        )
        self.assertEqual(checked.status_code, 200, checked.text)
        self.assertEqual(checked.headers["cache-control"], "no-store")
        self.assertFalse(checked.json()["data"]["valid"])
        self.assertEqual(checked.json()["data"]["code"], "name_invalid")
        rejected = await self.client.post(
          "/api/tools",
          json={"display_name": "名称校验", "name": name, "url": "http://localhost/"},
        )
        self.assertEqual(rejected.status_code, 422, rejected.text)
        self.assertEqual(rejected.json()["detail"]["code"], "name_invalid")
    for name in ("_tool", "Tool_123", "x" * 64):
      checked = await self.client.get("/api/tools/validate-name", params={"name": name})
      self.assertEqual(
        checked.json()["data"], {"valid": True, "code": None, "message": None}
      )
    self.assertEqual(self.path.read_bytes(), before)
    for name_fields in ({}, {"name": None}, {"name": []}):
      rejected = await self.client.post(
        "/api/tools",
        json={"display_name": "名称必填", "url": "http://localhost/", **name_fields},
      )
      self.assertEqual(rejected.status_code, 422, rejected.text)
      self.assertEqual(rejected.json()["detail"]["code"], "name_invalid")
    schema = (await self.client.get("/api/tools/schema/http")).json()["data"]
    self.assertIn("name", schema["required"])

  async def test_name_validation_excludes_self_and_checks_reserved_and_disabled_tools(
    self,
  ):
    created = await self.client.post(
      "/api/tools",
      json={
        "kind": "python",
        "display_name": "禁用工具",
        "name": "occupied",
        "code_path": "tools/example.py",
        "enabled": False,
      },
    )
    saved = (await self.read_created_tool(created))["data"]
    before = self.path.read_bytes()
    listed = (await self.client.get("/api/tools")).json()
    self.assertIn("add", listed["reserved_names"])
    self.assertIn("task", listed["reserved_names"])
    for name in ("occupied", "add", "task"):
      checked = await self.client.get("/api/tools/validate-name", params={"name": name})
      self.assertEqual(checked.json()["data"]["code"], "name_conflict")
      self.assertFalse(checked.json()["data"]["valid"])
    self_check = await self.client.get(
      "/api/tools/validate-name", params={"name": saved["name"], "tool_id": saved["id"]}
    )
    self.assertTrue(self_check.json()["data"]["valid"])
    missing = await self.client.get(
      "/api/tools/validate-name", params={"name": "occupied", "tool_id": "missing"}
    )
    self.assertEqual(missing.status_code, 404)
    self.assertEqual(self.path.read_bytes(), before)

  async def test_successful_name_check_does_not_reserve_name_or_bypass_save_check(self):
    checked = await self.client.get(
      "/api/tools/validate-name", params={"name": "new_tool"}
    )
    self.assertTrue(checked.json()["data"]["valid"])
    payload = {"display_name": "工具", "name": "new_tool", "url": "http://localhost/"}
    first = await self.client.post("/api/tools", json=payload)
    self.assertEqual(first.status_code, 201)
    before = self.path.read_bytes()
    second = await self.client.post("/api/tools", json=payload)
    self.assertEqual(second.status_code, 409)
    self.assertEqual(second.json()["detail"]["code"], "name_conflict")
    self.assertEqual(self.path.read_bytes(), before)
    self.path.write_text("{broken", encoding="utf-8")
    checked = await self.client.get(
      "/api/tools/validate-name", params={"name": "another"}
    )
    self.assertEqual(checked.status_code, 503)

  def http_service(self):
    requests = []

    class Handler(BaseHTTPRequestHandler):
      def do_GET(self):
        requests.append(self.path)
        status, mime, body = 200, "application/json", b"null"
        if self.path == "/error":
          status, body = 418, b'{"message":"teapot"}'
        elif self.path == "/redirect":
          status, body = 302, b'"redirect"'
        elif self.path == "/empty":
          status, body = 204, b""
        elif self.path == "/text":
          mime, body = "text/plain", "  精确文本\n".encode()
        elif self.path == "/binary":
          mime, body = "application/octet-stream", b"\x00\xff"
        elif self.path == "/large":
          mime, body = "text/plain", b"x" * (1024 * 1024 + 1)
        elif self.path == "/invalid":
          body = b'{"value":1e999}'
        elif self.path == "/slow":
          mime, body = "text/plain", b"abcdefghij"
        self.send_response(status)
        self.send_header("Content-Type", mime)
        if status == 302:
          self.send_header("Location", "/redirect-target")
        self.end_headers()
        try:
          if self.path == "/slow":
            for byte in body:
              self.wfile.write(bytes([byte]))
              self.wfile.flush()
              time.sleep(0.2)
          else:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
          pass

      def log_message(self, format, *args):
        pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    Thread(target=server.serve_forever, daemon=True).start()
    self.addCleanup(server.server_close)
    self.addCleanup(server.shutdown)
    return f"http://127.0.0.1:{server.server_port}", requests

  async def test_draft_test_uses_current_definition_without_saving(self):
    base, requests = self.http_service()
    original = (await self.client.get("/api/tools")).json()
    definition = {
      "kind": "http",
      "display_name": "未保存草稿",
      "name": "draft_tool",
      "url": base + "/text",
      "enabled": False,
      "input_schema": {"type": "object", "additionalProperties": False},
    }
    started = await self.client.post(
      "/api/tools/tests", json={"definition": definition, "inputs": {}}
    )
    self.assertEqual(started.status_code, 202, started.text)
    test_id = started.json()["data"]["test_id"]
    for _ in range(200):
      observed = (await self.client.get(f"/api/tools/tests/{test_id}")).json()["data"]
      if observed["status"] != "running":
        break
      await asyncio.sleep(0.02)
    self.assertEqual(observed["result"]["data"], "  精确文本\n")
    self.assertEqual(requests, ["/text"])

    self.assertEqual((await self.client.get("/api/tools")).json(), original)

    invalid = await self.client.post(
      "/api/tools/tests", json={"definition": definition, "inputs": {"extra": 1}}
    )
    test_id = invalid.json()["data"]["test_id"]
    for _ in range(200):
      observed = (await self.client.get(f"/api/tools/tests/{test_id}")).json()["data"]
      if observed["status"] != "running":
        break
      await asyncio.sleep(0.02)
    self.assertEqual(observed["result"]["error"]["code"], "input_validation")
    self.assertEqual(requests, ["/text"])

  async def test_edit_disable_draft_and_delete_preserve_saved_lifecycle(self):
    base, requests = self.http_service()
    payload = {
      "kind": "http",
      "name": "original_tool",
      "display_name": "原工具",
      "url": base + "/text",
    }
    created = await self.read_created_tool(
      await self.client.post("/api/tools", json=payload)
    )
    tool_id = created["data"]["id"]
    edited = {
      **payload,
      "name": "renamed_tool",
      "display_name": "改名",
      "enabled": False,
    }
    updated = await self.client.put(
      f"/api/tools/{tool_id}",
      json={"definition": edited, "version": created["version"]},
    )
    self.assertEqual(updated.status_code, 204, updated.text)
    saved = (await self.client.get(f"/api/tools/{tool_id}")).json()
    self.assertEqual(saved["data"]["id"], tool_id)
    self.assertEqual(saved["data"]["created_at"], created["data"]["created_at"])
    rejected = (
      await self.client.post(f"/api/tools/{tool_id}/execute", json={"inputs": {}})
    ).json()["data"]
    self.assertEqual(rejected["error"]["code"], "disabled")
    self.assertEqual(requests, [])
    tested = await self.client.post(
      "/api/tools/tests",
      json={
        "definition": {**edited, "url": base + "/empty"},
        "tool_id": tool_id,
        "inputs": {},
      },
    )
    self.assertEqual(tested.status_code, 202, tested.text)
    test_id = tested.json()["data"]["test_id"]
    for _ in range(200):
      observed = (await self.client.get(f"/api/tools/tests/{test_id}")).json()["data"]
      if observed["status"] != "running":
        break
      await asyncio.sleep(0.02)
    self.assertEqual(observed["status"], "success")
    self.assertEqual(requests, ["/empty"])
    self.assertEqual((await self.client.get(f"/api/tools/{tool_id}")).json(), saved)
    stale = await self.client.request(
      "DELETE", f"/api/tools/{tool_id}", json={"version": created["version"]}
    )
    self.assertEqual(stale.status_code, 409, stale.text)
    deleted = await self.client.request(
      "DELETE", f"/api/tools/{tool_id}", json={"version": saved["version"]}
    )
    self.assertEqual(deleted.status_code, 204, deleted.text)
    self.assertEqual((await self.client.get("/api/tools")).json()["data"], [])
    self.assertEqual((await self.client.get(f"/api/tools/{tool_id}")).status_code, 404)
    missing = (
      await self.client.post(f"/api/tools/{tool_id}/execute", json={"inputs": {}})
    ).json()["data"]
    self.assertEqual(missing["error"]["code"], "not_found")

  async def test_draft_and_update_cannot_bypass_system_fields_or_type_permissions(self):
    payload = {
      "kind": "http",
      "name": "secured_tool",
      "display_name": "工具",
      "url": "http://localhost/",
    }
    saved = await self.read_created_tool(
      await self.client.post("/api/tools", json=payload)
    )
    tool_id = saved["data"]["id"]
    for change in (
      {"kind": "python", "code_path": "user.py"},
      {"id": "forged"},
      {"created_at": saved["data"]["created_at"]},
    ):
      with self.subTest(change=change):
        definition = {**payload, **change}
        updated = await self.client.put(
          f"/api/tools/{tool_id}",
          json={"definition": definition, "version": saved["version"]},
        )
        draft = await self.client.post(
          "/api/tools/tests",
          json={"definition": definition, "tool_id": tool_id, "inputs": {}},
        )
        self.assertEqual(updated.json()["detail"]["code"], "read_only")
        self.assertEqual(draft.json()["detail"]["code"], "read_only")
    self.assertEqual((await self.client.get(f"/api/tools/{tool_id}")).json(), saved)

  async def test_mcp_manual_edits_and_draft_tests_protect_source_fields(self):
    payload = {
      "kind": "mcp",
      "display_name": "MCP 搜索",
      "name": "mcp_search",
      "server_id": "local",
      "remote_name": "search",
      "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}},
      "output_schema": {"type": "object", "properties": {"count": {"type": "integer"}}},
    }
    created = await self.client.post("/api/tools", json=payload)
    self.assertEqual(created.status_code, 201, created.text)
    saved = await self.read_created_tool(created)
    tool_id = saved["data"]["id"]
    changed_schema = {"type": "object", "properties": {"limit": {"type": "integer"}}}
    for change in (
      {"server_id": "another_server"},
      {"remote_name": "another_tool"},
      {"input_schema": changed_schema},
      {"output_schema": {"type": "string"}},
      {"output_schema": None},
      {"input_schema": changed_schema, "discovery_update": True},
    ):
      with self.subTest(change=change):
        definition = {**payload, **change}
        updated = await self.client.put(
          f"/api/tools/{tool_id}",
          json={"definition": definition, "version": saved["version"]},
        )
        draft = await self.client.post(
          "/api/tools/tests",
          json={"definition": definition, "tool_id": tool_id, "inputs": {}},
        )
        for response in (updated, draft):
          self.assertEqual(response.status_code, 422, response.text)
          self.assertEqual(response.json()["detail"]["code"], "read_only")
    self.assertEqual((await self.client.get(f"/api/tools/{tool_id}")).json(), saved)

    # Local edits may omit source fields, which must retain their saved values.
    editable = {
      "kind": "mcp",
      "display_name": "本地改名",
      "name": "renamed_search",
      "description": "本地用途",
      "enabled": False,
      "timeout_seconds": 12,
    }
    updated = await self.client.put(
      f"/api/tools/{tool_id}",
      json={"definition": editable, "version": saved["version"]},
    )
    self.assertEqual(updated.status_code, 204, updated.text)
    updated_saved = (await self.client.get(f"/api/tools/{tool_id}")).json()
    for field in (
      "server_id",
      "remote_name",
      "input_schema",
      "output_schema",
      "id",
      "created_at",
    ):
      self.assertEqual(updated_saved["data"][field], saved["data"][field])
    for field, value in editable.items():
      self.assertEqual(updated_saved["data"][field], value)
    draft = await self.client.post(
      "/api/tools/tests",
      json={"definition": editable, "tool_id": tool_id, "inputs": {}},
    )
    self.assertEqual(draft.status_code, 202, draft.text)
    self.assertEqual(
      (await self.client.get(f"/api/tools/{tool_id}")).json(), updated_saved
    )

  async def test_executable_definitions_recheck_enabled_and_deleted_tools(self):
    from shikigen.runtime.tool_library import ToolLibraryError

    library = self.app.state.runtime.tools
    payload = {
      "kind": "http",
      "name": "select_tool",
      "display_name": "工具",
      "url": "http://localhost/",
    }
    saved = await self.read_created_tool(
      await self.client.post("/api/tools", json=payload)
    )
    tool_id = saved["data"]["id"]
    self.assertEqual(
      (await library.get_executable_tool_definitions([tool_id]))[0].id, tool_id
    )
    disabled = await self.client.put(
      f"/api/tools/{tool_id}",
      json={"definition": {**payload, "enabled": False}, "version": saved["version"]},
    )
    self.assertEqual(disabled.status_code, 204)
    disabled_saved = (await self.client.get(f"/api/tools/{tool_id}")).json()
    with self.assertRaises(ToolLibraryError) as error:
      await library.get_executable_tool_definitions([tool_id])
    self.assertEqual(error.exception.code, "disabled")
    await self.client.request(
      "DELETE", f"/api/tools/{tool_id}", json={"version": disabled_saved["version"]}
    )
    with self.assertRaises(ToolLibraryError) as error:
      await library.get_executable_tool_definitions([tool_id])
    self.assertEqual(error.exception.code, "not_found")

  def echo_service(self):
    requests = []

    class Handler(BaseHTTPRequestHandler):
      def handle_request(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        observed = {
          "method": self.command,
          "path": self.path,
          "headers": dict(self.headers),
          "body": body.decode(),
        }
        requests.append(observed)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        if self.command != "HEAD":
          self.wfile.write(json.dumps(observed).encode())

      do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = do_OPTIONS = (
        handle_request
      )

      def log_message(self, format, *args):
        pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    Thread(target=server.serve_forever, daemon=True).start()
    self.addCleanup(server.server_close)
    self.addCleanup(server.shutdown)
    return f"http://127.0.0.1:{server.server_port}", requests

  async def test_http_mapping_sends_real_methods_locations_and_json_types(self):
    base, requests = self.echo_service()
    schema = {
      "type": "object",
      "additionalProperties": False,
      "required": ["path"],
      "properties": {
        "path": {
          "type": "object",
          "required": ["id"],
          "properties": {"id": {"type": "string"}},
        },
        "query": {
          "type": "object",
          "properties": {
            "id": {"type": "integer"},
            "tags": {"type": "array", "items": {"type": "string"}},
            "csv": {"type": "array", "items": {"type": "integer"}},
            "flag": {"type": "boolean"},
            "empty": {"type": "string"},
          },
        },
        "headers": {"type": "object", "properties": {"flag": {"type": "boolean"}}},
        "body": {
          "type": ["object", "null"],
          "properties": {"nested": {"type": "array"}},
        },
      },
    }
    parameters = [
      {"location": location, "input_name": name, "name": target, **options}
      for location, name, target, options in (
        ("path", "id", "item", {}),
        ("query", "id", "id", {}),
        ("query", "tags", "tags", {}),
        ("query", "csv", "csv", {"explode": False}),
        ("query", "flag", "flag", {}),
        ("query", "empty", "empty", {}),
        ("headers", "flag", "X-Flag", {}),
      )
    ]
    inputs = {
      "path": {"id": "a/b &"},
      "query": {"id": 0, "tags": ["a", "b"], "csv": [1, 2], "flag": False, "empty": ""},
      "headers": {"flag": False},
      "body": {"nested": [None, False, 0, "", [], {}]},
    }
    for method in ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"):
      with self.subTest(method=method):
        created = await self.client.post(
          "/api/tools",
          json={
            "display_name": "带参请求",
            "name": f"mapped_{method}",
            "url": base + "/items/{item}?fixed=1",
            "method": method,
            "headers": {"X-Fixed": "fixed"},
            "parameters": parameters,
            "input_schema": schema,
          },
        )
        self.assertEqual(created.status_code, 201, created.text)
        result = (
          await self.client.post(
            f"/api/tools/{created.json()['data']['id']}/execute",
            json={"inputs": inputs},
          )
        ).json()["data"]
        self.assertEqual(result["status"], "success", result)
        actual = requests[-1]
        self.assertEqual(actual["method"], method)
        self.assertEqual(urlsplit(actual["path"]).path, "/items/a%2Fb%20%26")
        self.assertEqual(
          parse_qs(urlsplit(actual["path"]).query, keep_blank_values=True),
          {
            "fixed": ["1"],
            "id": ["0"],
            "tags": ["a", "b"],
            "csv": ["1,2"],
            "flag": ["false"],
            "empty": [""],
          },
        )
        self.assertEqual(actual["headers"]["X-Fixed"], "fixed")
        self.assertEqual(actual["headers"]["X-Flag"], "false")
        self.assertEqual(actual["headers"]["Content-Type"], "application/json")
        self.assertEqual(json.loads(actual["body"]), inputs["body"])

  async def execute_http(self, url, **options):
    saved = await self.client.post(
      "/api/tools",
      json={
        "display_name": "HTTP 行为",
        "name": f"http_{len((await self.client.get('/api/tools')).json()['data'])}",
        "url": url,
        **options,
      },
    )
    self.assertEqual(saved.status_code, 201, saved.text)
    return (
      await self.client.post(
        f"/api/tools/{saved.json()['data']['id']}/execute",
        json={"inputs": {}},
      )
    ).json()["data"]

  async def test_http_definition_rejects_inconsistent_or_unsupported_requests(self):
    base, requests = self.echo_service()
    scalar = {"type": "string"}
    group = {"type": "object", "required": ["id"], "properties": {"id": scalar}}
    schema = {"type": "object", "required": ["path"], "properties": {"path": group}}
    mapping = {"location": "path", "input_name": "id", "name": "id"}
    valid = {
      "display_name": "配置校验",
      "name": "validation",
      "url": base + "/{id}",
      "input_schema": schema,
      "parameters": [mapping],
    }
    for override in (
      {"method": "TRACE"},
      {"parameters": []},
      {"url": base + "/{other}"},
      {"url": "http://{id}.example.test/"},
      {"url": base + "/?q={id}"},
      {"url": base + "/{id"},
      {"parameters": [mapping, mapping]},
      {"parameters": [{**mapping, "style": "form"}]},
      {"parameters": [{**mapping, "location": "cookie"}]},
      {"input_schema": {**schema, "required": []}},
      {"input_schema": {**schema, "properties": {"path": {**group, "required": []}}}},
      {
        "input_schema": {
          **schema,
          "properties": {
            "path": {**group, "properties": {"id": {"type": "array", "items": scalar}}}
          },
        }
      },
      {"input_schema": {"type": "object", "properties": {"cookie": group}}},
      {"headers": {"Bad Header": "x"}},
      {"headers": {"X-Test": "a\r\nb"}},
      {"headers": {"X-Test": "中文"}},
      {"headers": {"Content-Length": "10"}},
    ):
      with self.subTest(override=override):
        before = self.path.read_bytes()
        rejected = await self.client.post("/api/tools", json={**valid, **override})
        self.assertEqual(rejected.status_code, 422, rejected.text)
        self.assertEqual(rejected.json()["detail"]["code"], "definition_invalid")
        self.assertEqual(self.path.read_bytes(), before)
    self.assertEqual(requests, [])

  async def test_path_dot_segments_remain_parameters_instead_of_changing_target(self):
    base, requests = self.echo_service()
    created = await self.client.post(
      "/api/tools",
      json={
        "display_name": "路径点段",
        "name": "dot_segments",
        "url": base + "/items/{id}/details",
        "input_schema": {
          "type": "object",
          "required": ["path"],
          "properties": {
            "path": {
              "type": "object",
              "required": ["id"],
              "properties": {"id": {"type": "string"}},
            }
          },
        },
        "parameters": [{"location": "path", "input_name": "id", "name": "id"}],
      },
    )
    self.assertEqual(created.status_code, 201, created.text)
    for value, path in ((".", "/items/%2E/details"), ("..", "/items/%2E%2E/details")):
      result = (
        await self.client.post(
          f"/api/tools/{created.json()['data']['id']}/execute",
          json={"inputs": {"path": {"id": value}}},
        )
      ).json()["data"]
      self.assertEqual(result["status"], "success", result)
      self.assertEqual(requests[-1]["path"], path)

  async def test_http_optional_null_falsy_and_constraints_are_not_coerced(self):
    base, requests = self.echo_service()
    schema = {
      "type": "object",
      "additionalProperties": False,
      "properties": {
        "query": {
          "type": "object",
          "properties": {
            "value": {
              "type": ["string", "null"],
              "default": "injected",
              "maxLength": 3,
            },
            "count": {"type": "integer", "minimum": 0, "maximum": 2},
            "enum": {"type": "string", "enum": ["yes", "no"]},
            "tags": {
              "type": "array",
              "maxItems": 2,
              "uniqueItems": True,
              "items": {"type": "integer"},
            },
          },
        },
        "headers": {
          "type": "object",
          "properties": {"value": {"type": ["string", "null"]}},
        },
        "body": {
          "type": ["object", "null"],
          "required": ["nested"],
          "properties": {
            "nested": {"type": "array", "minItems": 1, "items": {"type": "boolean"}},
            "mail": {"type": "string", "format": "email"},
          },
        },
      },
    }
    parameters = [
      {"location": group, "input_name": name, "name": name}
      for group, names in (
        ("query", ("value", "count", "enum", "tags")),
        ("headers", ("value",)),
      )
      for name in names
    ]
    created = await self.client.post(
      "/api/tools",
      json={
        "display_name": "精确输入",
        "name": "exact_inputs",
        "url": base,
        "method": "POST",
        "input_schema": schema,
        "parameters": parameters,
      },
    )
    self.assertEqual(created.status_code, 201, created.text)
    endpoint = f"/api/tools/{created.json()['data']['id']}/execute"
    for inputs in (
      {},
      {"body": None},
      {"body": {"nested": [False], "mail": "not-an-email"}},
      {"query": {"value": "", "count": 0, "tags": []}},
    ):
      result = (await self.client.post(endpoint, json={"inputs": inputs})).json()[
        "data"
      ]
      self.assertEqual(result["status"], "success", result)
    self.assertEqual(requests[0]["body"], "")
    self.assertNotIn("Content-Type", requests[0]["headers"])
    self.assertEqual(requests[0]["path"], "/")
    self.assertEqual(requests[1]["body"], "null")
    self.assertEqual(
      json.loads(requests[2]["body"]), {"nested": [False], "mail": "not-an-email"}
    )
    self.assertEqual(
      parse_qs(urlsplit(requests[3]["path"]).query, keep_blank_values=True),
      {"value": [""], "count": ["0"]},
    )
    before = len(requests)
    for inputs in (
      {"query": {"value": None}},
      {"headers": {"value": None}},
      {"query": {"value": "long"}},
      {"query": {"count": "1"}},
      {"query": {"count": True}},
      {"query": {"count": 3}},
      {"query": {"enum": "other"}},
      {"query": {"tags": [1, 1]}},
      {"query": {"tags": [1, 2, 3]}},
      {"body": {}},
      {"body": {"nested": []}},
      {"body": {"nested": ["false"]}},
      {"query": {"unknown": 1}},
      {"headers": {"value": "a\r\nb"}},
    ):
      with self.subTest(inputs=inputs):
        result = (await self.client.post(endpoint, json={"inputs": inputs})).json()[
          "data"
        ]
        self.assertEqual(result["error"]["code"], "input_validation", result)
    self.assertEqual(len(requests), before)

  async def test_schema_dialects_references_and_unsupported_constraints_are_explicit(
    self,
  ):
    base, requests = self.echo_service()
    for index, dialect in enumerate(
      (
        "http://json-schema.org/draft-07/schema#",
        "https://json-schema.org/draft/2020-12/schema",
      )
    ):
      schema = {
        "$schema": dialect,
        "type": "object",
        "properties": {
          "body": {
            "type": "object",
            "required": ["value"],
            "properties": {"value": {"$ref": "#/$defs/value"}},
          }
        },
        "$defs": {
          "value": {
            "type": "string",
            "pattern": "^[a-z]+$",
            "minLength": 2,
            "format": "email",
          }
        },
      }
      created = await self.client.post(
        "/api/tools",
        json={
          "display_name": "方言与引用",
          "name": f"dialect_{index}",
          "url": base,
          "method": "POST",
          "input_schema": schema,
          "output_schema": {"type": "integer"},
        },
      )
      self.assertEqual(created.status_code, 201, created.text)
      endpoint = f"/api/tools/{created.json()['data']['id']}/execute"
      result = (
        await self.client.post(endpoint, json={"inputs": {"body": {"value": "okay"}}})
      ).json()["data"]
      self.assertEqual(result["status"], "success", result)
      self.assertIsInstance(
        result["data"], dict
      )  # Output schema is documentation only.
      before = len(requests)
      invalid = (
        await self.client.post(endpoint, json={"inputs": {"body": {"value": "X"}}})
      ).json()["data"]
      self.assertEqual(invalid["error"]["code"], "input_validation")
      self.assertEqual(len(requests), before)
    for node in (
      {"type": "string", "nullable": True},
      {"type": "string", "madeUpConstraint": 1},
      {"anyOf": [{"type": "string"}, {"type": "integer"}]},
      {"$ref": "#/missing"},
      {"$ref": "https://example.test/schema"},
      {"type": "array", "items": [{"type": "string"}]},
      {"$ref": "#/properties/body"},
      {"type": "string", "pattern": "["},
    ):
      with self.subTest(node=node):
        rejected = await self.client.post(
          "/api/tools",
          json={
            "display_name": "不支持结构",
            "name": "unsupported_schema",
            "url": base,
            "input_schema": {"type": "object", "properties": {"body": node}},
          },
        )
        self.assertEqual(rejected.status_code, 422, rejected.text)
    rejected = await self.client.post(
      "/api/tools",
      json={
        "display_name": "未知方言",
        "name": "unknown_dialect",
        "url": base,
        "input_schema": {"$schema": "https://example.test/dialect", "type": "object"},
      },
    )
    self.assertEqual(rejected.status_code, 422)

  async def test_http_errors_keep_response_and_redirects_are_not_followed(self):
    base, requests = self.http_service()
    result = await self.execute_http(base + "/error")
    self.assertEqual(result["status"], "error")
    self.assertEqual(result["data"], {"message": "teapot"})
    self.assertEqual(result["error"]["code"], "http_status")
    self.assertEqual(result["details"]["status_code"], 418)
    result = await self.execute_http(base + "/redirect")
    self.assertEqual(result["status"], "error")
    self.assertEqual(result["data"], "redirect")
    self.assertEqual(result["details"]["status_code"], 302)
    self.assertEqual(requests, ["/error", "/redirect"])

  async def test_empty_and_text_keep_types_and_unsupported_results_fail(self):
    base, _ = self.http_service()
    self.assertEqual((await self.execute_http(base + "/empty"))["data"], "")
    self.assertEqual((await self.execute_http(base + "/text"))["data"], "  精确文本\n")
    for path, code in (
      ("binary", "unsupported_response"),
      ("large", "output_limit"),
      ("invalid", "invalid_response"),
    ):
      with self.subTest(path=path):
        result = await self.execute_http(base + "/" + path)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"]["code"], code)
        self.assertIsNone(result["data"])

  async def test_budget_covers_response_reading_and_disabled_tools_can_be_tested(self):
    base, _ = self.http_service()
    result = await self.execute_http(base + "/slow", timeout_seconds=1)
    self.assertEqual(result["status"], "timeout")
    self.assertIsNone(result["data"])
    self.assertGreaterEqual(result["duration_ms"], 950)
    self.assertLess(result["duration_ms"], 1800)
    saved = (
      await self.client.post(
        "/api/tools",
        json={
          "display_name": "禁用仍可手动测试",
          "name": "disabled_test",
          "url": base,
          "enabled": False,
        },
      )
    ).json()["data"]
    normal = await self.client.post(
      f"/api/tools/{saved['id']}/execute", json={"inputs": {}}
    )
    self.assertEqual(normal.json()["data"]["error"]["code"], "disabled")
    test = await self.client.post(
      f"/api/tools/{saved['id']}/tests", json={"inputs": {}}
    )
    self.assertEqual(test.status_code, 202)
    for _ in range(100):
      observed = (
        await self.client.get(f"/api/tools/tests/{test.json()['data']['test_id']}")
      ).json()["data"]
      if observed["status"] != "running":
        break
      await asyncio.sleep(0.01)
    self.assertEqual(observed["status"], "success")

  async def test_invalid_config_and_inputs_never_execute_cached_definitions(self):
    base, requests = self.http_service()
    saved = (
      await self.client.post(
        "/api/tools",
        json={
          "display_name": "有效配置",
          "name": "valid_config",
          "url": base,
        },
      )
    ).json()["data"]
    response = await self.client.post(
      f"/api/tools/{saved['id']}/execute", json={"inputs": {"extra": 1}}
    )
    self.assertEqual(response.json()["data"]["error"]["code"], "input_validation")
    self.assertEqual(requests, [])
    for override in (
      {"timeout_seconds": 0},
      {"timeout_seconds": 301},
      {"url": "ftp://example.com"},
      {"name": []},
      {"display_name": 3},
      {"input_schema": {"type": "array"}},
      {"input_schema": {"type": "object", "$ref": "https://example.com/schema"}},
    ):
      before = self.path.read_bytes()
      response = await self.client.post(
        "/api/tools",
        json={"display_name": "错误", "name": "invalid", "url": base, **override},
      )
      self.assertEqual(response.status_code, 422, response.text)
      self.assertEqual(self.path.read_bytes(), before)
    self.path.write_text("{broken", encoding="utf-8")
    listed = await self.client.get("/api/tools")
    self.assertEqual(listed.status_code, 503)
    executed = await self.client.post(
      f"/api/tools/{saved['id']}/execute", json={"inputs": {}}
    )
    self.assertEqual(executed.json()["data"]["error"]["code"], "config_read")
    self.assertEqual(requests, [])

  async def test_failed_replace_preserves_original_and_literal_library(self):
    original = {
      **self.original,
      "tool_library": {"tools": [], "mcp_connections": {"reserved": "$LITERAL"}},
    }
    self.path.write_text(json.dumps(original), encoding="utf-8")
    before = self.path.read_bytes()
    with patch("os.replace", side_effect=PermissionError("fixture file is open")):
      failed = await self.client.post(
        "/api/tools",
        json={"display_name": "失败", "name": "failure", "url": "http://localhost/"},
      )
    self.assertEqual(failed.status_code, 503)
    self.assertEqual(self.path.read_bytes(), before)
    saved = await self.client.post(
      "/api/tools",
      json={"display_name": "成功", "name": "success", "url": "http://localhost/"},
    )
    self.assertEqual(saved.status_code, 201)
    self.assertEqual(
      json.loads(self.path.read_text())["tool_library"]["mcp_connections"],
      {"reserved": "$LITERAL"},
    )

  async def test_commit_is_reported_even_if_external_change_prevents_reread(self):
    replace = os.replace

    def replace_then_external_remove(source, target):
      replace(source, target)
      Path(target).unlink()

    with patch("os.replace", side_effect=replace_then_external_remove):
      saved = await self.client.post(
        "/api/tools",
        json={
          "display_name": "提交后外部变化",
          "name": "external_change",
          "url": "http://localhost/",
        },
      )
    self.assertEqual(saved.status_code, 201, saved.text)
    self.assertTrue(saved.json()["data"]["id"])
    self.assertEqual((await self.client.get("/api/tools")).status_code, 503)
