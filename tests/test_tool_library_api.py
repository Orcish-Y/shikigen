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
    saved = response.json()["data"]
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
        tool = created.json()["data"]
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
    self.assertEqual(updated.status_code, 200, updated.text)
    updated_tool = updated.json()["data"]
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
    tool = created.json()["data"]
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
        "version": created.json()["version"],
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
    second = await self.client.post(
      "/api/tools", json={**payload, "name": "custom_add_2"}
    )
    self.assertEqual(first.status_code, 201)
    self.assertEqual(second.status_code, 201)
    self.assertNotEqual(first.json()["data"]["name"], "add")
    self.assertNotEqual(first.json()["data"]["name"], second.json()["data"]["name"])
    before = self.path.read_bytes()
    for name in ("add", first.json()["data"]["name"]):
      response = await self.client.post("/api/tools", json={**payload, "name": name})
      self.assertEqual(response.status_code, 409)
      self.assertEqual(response.json()["detail"]["code"], "name_conflict")
    self.assertEqual(self.path.read_bytes(), before)
    saved = first.json()["data"]
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
        "version": second.json()["version"],
      },
    )
    self.assertEqual(response.status_code, 200)
    self.assertEqual(response.json()["data"]["id"], saved["id"])
    self.assertEqual(response.json()["data"]["created_at"], saved["created_at"])
    stale = await self.client.put(
      f"/api/tools/{saved['id']}",
      json={
        "definition": edited,
        "version": first.json()["version"],
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
    saved = (
      await self.client.post(
        "/api/tools",
        json={
          "kind": "python",
          "display_name": "禁用工具",
          "name": "occupied",
          "code_path": "tools/example.py",
          "enabled": False,
        },
      )
    ).json()["data"]
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
