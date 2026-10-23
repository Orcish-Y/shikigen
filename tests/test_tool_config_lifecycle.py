"""配置提交点、外部修改和调用快照：公开 API 与真实临时文件。"""

import asyncio
import json
import os
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from threading import Event
from unittest.mock import patch

import httpx
from shikigen.app_config import load_app_config
from shikigen.persistence import ChatStore
from shikigen.runtime.composition import assemble_runtime

from app.server import create_app


class ToolConfigLifecycleTests(unittest.IsolatedAsyncioTestCase):
  async def asyncSetUp(self):
    directory = tempfile.TemporaryDirectory()
    self.addCleanup(directory.cleanup)
    self.path = Path(directory.name) / "config.json"
    self.path.write_text(json.dumps({"model": {}, "mcp": {}}), encoding="utf-8")
    store = await ChatStore.open(Path(directory.name) / "test.db")
    self.addAsyncCleanup(store.close)
    self.runtime = assemble_runtime(
      config=load_app_config(self.path), agent=None, chat_store=store
    )
    app = create_app(runtime=self.runtime)
    context = app.router.lifespan_context(app)
    await context.__aenter__()
    self.addAsyncCleanup(context.__aexit__, None, None, None)
    self.client = httpx.AsyncClient(
      transport=httpx.ASGITransport(app=app), base_url="http://test"
    )
    self.addAsyncCleanup(self.client.aclose)
    self.addAsyncCleanup(self.runtime.lifecycle.shutdown)

  def python(self, source):
    return {
      "kind": "python",
      "name": "calculate",
      "display_name": "计算",
      "source": source,
    }

  async def create(self, definition):
    created = await self.client.post("/api/tools", json=definition)
    self.assertEqual(created.status_code, 201, created.text)
    tool_id = created.json()["data"]["id"]
    return (await self.client.get(f"/api/tools/{tool_id}")).json()

  async def execute(self, saved, inputs=None):
    response = await self.client.post(
      f"/api/tools/{saved['data']['id']}/execute", json={"inputs": inputs or {}}
    )
    self.assertEqual(response.status_code, 200, response.text)
    return response.json()["data"]

  async def test_external_source_changes_version_and_blocks_stale_save_and_delete(self):
    saved = await self.create(self.python("def main(): return 'old'\n"))
    tool_id = saved["data"]["id"]
    code = self.path.parent / saved["data"]["code_path"]
    code.write_text("def main(): return 'external'\n", encoding="utf-8")
    current = (await self.client.get(f"/api/tools/{tool_id}")).json()
    self.assertNotEqual(current["version"], saved["version"])
    self.assertEqual((await self.execute(saved))["data"], "external")
    before = self.path.read_bytes()
    for method, payload in (
      ("PUT", {"definition": self.python("def main(): return 'draft'\n")}),
      ("DELETE", {}),
    ):
      response = await self.client.request(
        method, f"/api/tools/{tool_id}", json={**payload, "version": saved["version"]}
      )
      self.assertEqual(response.status_code, 409, response.text)
      self.assertIn(tool_id, response.json()["detail"]["resource_ids"])
      self.assertEqual(self.path.read_bytes(), before)
      self.assertEqual(
        code.read_text(encoding="utf-8"), "def main(): return 'external'\n"
      )

  @unittest.skipUnless(os.name == "nt", "Windows 文件共享与替换行为")
  async def test_cleanup_failure_keeps_success_and_retries_on_later_writes(self):
    saved = await self.create(self.python("def main(): return 'old'\n"))
    tool_id = saved["data"]["id"]
    old_code = self.path.parent / saved["data"]["code_path"]
    user_file = old_code.parent / "example.py"
    user_file.write_text("# user owned", encoding="utf-8")
    with old_code.open("rb"):
      with self.assertLogs("shikigen.persistence.python_source_store", level="WARNING"):
        updated = await self.client.put(
          f"/api/tools/{tool_id}",
          json={
            "definition": self.python("def main(): return 'new'\n"),
            "version": saved["version"],
          },
        )
      self.assertEqual(updated.status_code, 204, updated.text)
      self.assertEqual(updated.content, b"")
      self.assertTrue(old_code.exists())
      self.assertEqual((await self.execute(saved))["data"], "new")
      with self.assertLogs("shikigen.persistence.python_source_store", level="WARNING"):
        created = await self.client.post(
          "/api/tools",
          json={
            "name": "created_while_locked",
            "display_name": "新建成功",
            "url": "http://localhost/",
          },
        )
      self.assertEqual(created.status_code, 201, created.text)
      self.assertEqual(set(created.json()), {"data"})
      self.assertEqual(set(created.json()["data"]), {"id"})
    current = (await self.client.get(f"/api/tools/{tool_id}")).json()
    new_code = self.path.parent / current["data"]["code_path"]
    with new_code.open("rb"):
      with self.assertLogs("shikigen.persistence.python_source_store", level="WARNING"):
        deleted = await self.client.request(
          "DELETE", f"/api/tools/{tool_id}", json={"version": current["version"]}
        )
      self.assertEqual(deleted.status_code, 204, deleted.text)
      self.assertEqual(deleted.content, b"")
      self.assertEqual(
        (await self.client.get(f"/api/tools/{tool_id}")).status_code, 404
      )
    self.assertTrue(user_file.exists())
    await self.create(self.python("def main(): return 'later'\n"))
    self.assertFalse(old_code.exists())
    self.assertFalse(new_code.exists())

  @unittest.skipUnless(os.name == "nt", "Windows 文件共享与替换行为")
  async def test_failed_config_replace_preserves_raw_document_and_old_code(self):
    saved = await self.create(self.python("def main(): return 'old'\n"))
    raw = json.loads(self.path.read_text(encoding="utf-8"))
    raw["model"] = {"api_key": "$EXAMPLE_KEY"}
    raw["other"] = {"literal": ["$KEEP_ME", {"nested": True}]}
    self.path.write_text(json.dumps(raw), encoding="utf-8")
    current = (await self.client.get(f"/api/tools/{saved['data']['id']}")).json()
    before = self.path.read_bytes()
    with self.path.open("rb"):
      response = await self.client.put(
        f"/api/tools/{saved['data']['id']}",
        json={
          "definition": self.python("def main(): return 'new'\n"),
          "version": current["version"],
        },
      )
    self.assertEqual(response.status_code, 503, response.text)
    self.assertEqual(response.json()["detail"]["code"], "config_write")
    self.assertEqual(self.path.read_bytes(), before)
    self.assertEqual((await self.execute(saved))["data"], "old")
    saved_again = await self.client.put(
      f"/api/tools/{saved['data']['id']}",
      json={
        "definition": self.python("def main(): return 'new'\n"),
        "version": current["version"],
      },
    )
    self.assertEqual(saved_again.status_code, 204, saved_again.text)
    after = json.loads(self.path.read_text(encoding="utf-8"))
    self.assertEqual(after["model"], raw["model"])
    self.assertEqual(after["other"], raw["other"])

  async def test_openapi_batch_uses_preview_version_and_never_partially_commits(self):
    document = json.dumps(
      {
        "openapi": "3.1.0",
        "info": {"title": "Example", "version": "1"},
        "servers": [{"url": "https://example.test"}],
        "paths": {
          path: {
            "get": {
              "operationId": name,
              "summary": name,
              "description": "Example operation",
              "responses": {"200": {"description": "ok"}},
            }
          }
          for path, name in (("/one", "one"), ("/two", "two"))
        },
      }
    )
    preview = (
      await self.client.post("/api/tools/openapi/preview", json={"document": document})
    ).json()
    selections = [
      {"operation_key": item["key"], "definition": {**item["definition"], "name": name}}
      for item, name in zip(preview["data"]["operations"], ["one", "two"], strict=True)
    ]
    await self.create(self.python("def main(): return 1\n"))
    before = self.path.read_bytes()
    stale = await self.client.post(
      "/api/tools/openapi/imports",
      json={"document": document, "tools": selections, "version": preview["version"]},
    )
    self.assertEqual(stale.status_code, 409, stale.text)
    self.assertEqual(self.path.read_bytes(), before)
    current = (await self.client.get("/api/tools")).json()["version"]
    selections[1]["definition"]["name"] = "one"
    invalid = await self.client.post(
      "/api/tools/openapi/imports",
      json={"document": document, "tools": selections, "version": current},
    )
    self.assertEqual(invalid.status_code, 409, invalid.text)
    self.assertEqual(self.path.read_bytes(), before)
    selections[1]["definition"]["name"] = "two"
    accepted = await self.client.post(
      "/api/tools/openapi/imports",
      json={"document": document, "tools": selections, "version": current},
    )
    self.assertEqual(accepted.status_code, 201, accepted.text)
    self.assertEqual(len(accepted.json()["data"]), 2)

  async def test_write_failures_and_change_during_preparation_preserve_old_definition(
    self,
  ):
    saved = await self.create(self.python("def main(): return 'old'\n"))
    tool_id = saved["data"]["id"]
    before = self.path.read_bytes()
    definition = self.python("def main(): return 'new'\n")
    for boundary in ("os.fsync", "tempfile.NamedTemporaryFile"):
      with (
        self.subTest(boundary=boundary),
        patch(boundary, side_effect=OSError("disk failure")),
      ):
        response = await self.client.put(
          f"/api/tools/{tool_id}",
          json={"definition": definition, "version": saved["version"]},
        )
      self.assertEqual(response.status_code, 503, response.text)
      self.assertEqual(self.path.read_bytes(), before)
      self.assertEqual((await self.execute(saved))["data"], "old")
    temporary_file = tempfile.NamedTemporaryFile

    @contextmanager
    def external_edit_after_temporary_file(**kwargs):
      with temporary_file(**kwargs) as stream:
        yield stream
      raw = json.loads(self.path.read_text(encoding="utf-8"))
      raw["tool_library"]["tools"][0]["description"] = "external edit"
      self.path.write_text(json.dumps(raw), encoding="utf-8")

    with patch("tempfile.NamedTemporaryFile", external_edit_after_temporary_file):
      response = await self.client.put(
        f"/api/tools/{tool_id}",
        json={"definition": definition, "version": saved["version"]},
      )
    self.assertEqual(response.status_code, 409, response.text)
    self.assertEqual(
      (await self.client.get(f"/api/tools/{tool_id}")).json()["data"]["description"],
      "external edit",
    )
    self.assertEqual((await self.execute(saved))["data"], "old")

  async def test_python_running_call_survives_replacement_disable_and_delete(self):
    arrived, release = asyncio.Event(), asyncio.Event()

    async def block(reader, writer):
      arrived.set()
      await release.wait()
      writer.write(b"x")
      await writer.drain()
      writer.close()
      await writer.wait_closed()

    server = await asyncio.start_server(block, "127.0.0.1", 0)
    self.addCleanup(server.close)
    self.addCleanup(release.set)
    port = server.sockets[0].getsockname()[1]
    old_source = (
      "import socket\ndef main():\n"
      f"  with socket.create_connection(('127.0.0.1', {port})) as channel:\n"
      "    channel.recv(1)\n  return 'old'\n"
    )
    saved = await self.create(self.python(old_source))
    tool_id = saved["data"]["id"]
    old_code = self.path.parent / saved["data"]["code_path"]
    started = await self.client.post(f"/api/tools/{tool_id}/tests", json={"inputs": {}})
    self.assertEqual(started.status_code, 202, started.text)
    await asyncio.wait_for(arrived.wait(), 5)
    updated = await self.client.put(
      f"/api/tools/{tool_id}",
      json={
        "definition": {**self.python("def main(): return 'new'\n"), "enabled": False},
        "version": saved["version"],
      },
    )
    self.assertEqual(updated.status_code, 204, updated.text)
    self.assertFalse(old_code.exists())
    self.assertEqual((await self.execute(saved))["error"]["code"], "disabled")
    current = (await self.client.get(f"/api/tools/{tool_id}")).json()
    deleted = await self.client.request(
      "DELETE", f"/api/tools/{tool_id}", json={"version": current["version"]}
    )
    self.assertEqual(deleted.status_code, 204, deleted.text)
    self.assertEqual((await self.execute(saved))["error"]["code"], "not_found")
    release.set()
    async with asyncio.timeout(5):
      while True:
        snapshot = (
          await self.client.get("/api/tools/tests/" + started.json()["data"]["test_id"])
        ).json()["data"]
        if snapshot["status"] != "running":
          break
        await asyncio.sleep(0.01)
    self.assertEqual(snapshot["result"]["data"], "old", snapshot)

  async def test_bad_config_and_bad_source_never_execute_cached_content(self):
    saved = await self.create(self.python("def main(value: int): return value\n"))
    tool_id = saved["data"]["id"]
    content = self.path.read_bytes()
    for invalid in (None, b"invalid JSON", b"[]", b'{"tool_library":{"tools":[{}]}}'):
      if invalid is None:
        self.path.unlink()
      else:
        self.path.write_bytes(invalid)
      self.assertEqual((await self.client.get("/api/tools")).status_code, 503)
      result = await self.execute(saved, {"value": 1})
      self.assertEqual(result["error"]["code"], "config_read")
      self.path.write_bytes(content)
    code = self.path.parent / saved["data"]["code_path"]
    code.write_text("def main(other: str): return other\n", encoding="utf-8")
    result = await self.execute(saved, {"value": 1})
    self.assertEqual(result["status"], "error")
    self.assertIn(tool_id, result["error"]["message"])
    # 不兼容源码仍可读取、重新解析并显式保存。
    detail = await self.client.get(f"/api/tools/{tool_id}")
    self.assertEqual(detail.status_code, 200, detail.text)
    repaired = await self.client.put(
      f"/api/tools/{tool_id}",
      json={
        "definition": self.python(detail.json()["data"]["source"]),
        "version": detail.json()["version"],
      },
    )
    self.assertEqual(repaired.status_code, 204, repaired.text)
    self.assertEqual(
      (await self.execute(saved, {"other": "repaired"}))["data"], "repaired"
    )
    current = (await self.client.get(f"/api/tools/{tool_id}")).json()
    (self.path.parent / current["data"]["code_path"]).unlink()
    missing = await self.client.get(f"/api/tools/{tool_id}")
    self.assertEqual(missing.status_code, 503, missing.text)
    self.assertEqual(missing.json()["detail"]["resource_ids"], [tool_id])

  async def test_reading_source_finishes_before_save_can_clean_its_path(self):
    saved = await self.create(self.python("def main(): return 'snapshot'\n"))
    source_path = self.path.parent / saved["data"]["code_path"]
    reading, release = Event(), Event()
    read_text = Path.read_text

    def blocked_read(path, *args, **kwargs):
      if path == source_path:
        reading.set()
        if not release.wait(5):
          raise TimeoutError("test source read was not released")
      return read_text(path, *args, **kwargs)

    self.addCleanup(release.set)
    with patch.object(Path, "read_text", blocked_read):
      invocation = asyncio.create_task(self.execute(saved))
      self.assertTrue(await asyncio.to_thread(reading.wait, 5))
      update = asyncio.create_task(
        self.client.put(
          f"/api/tools/{saved['data']['id']}",
          json={
            "definition": self.python("def main(): return 'new'\n"),
            "version": saved["version"],
          },
        )
      )
      await asyncio.sleep(0.05)
      release.set()
      self.assertEqual((await invocation)["data"], "snapshot")
      self.assertEqual((await update).status_code, 204)
    self.assertFalse(source_path.exists())
    self.assertEqual((await self.execute(saved))["data"], "new")

  async def test_cleanup_respects_external_reference_written_after_commit(self):
    saved = await self.create(self.python("def main(): return 'retained'\n"))
    code = self.path.parent / saved["data"]["code_path"]
    replace = os.replace

    def replace_then_reference_old_source(source, target):
      replace(source, target)
      raw = json.loads(Path(target).read_text(encoding="utf-8"))
      raw["tool_library"]["tools"][0]["code_path"] = saved["data"]["code_path"]
      Path(target).write_text(json.dumps(raw), encoding="utf-8")

    with patch("os.replace", replace_then_reference_old_source):
      updated = await self.client.put(
        f"/api/tools/{saved['data']['id']}",
        json={
          "definition": self.python("def main(): return 'submitted'\n"),
          "version": saved["version"],
        },
      )
    self.assertEqual(updated.status_code, 204, updated.text)
    self.assertTrue(code.exists())
    self.assertEqual((await self.execute(saved))["data"], "retained")

  async def test_cleanup_directory_read_failure_is_logged_and_retried(self):
    saved = await self.create(self.python("def main(): return 'old'\n"))
    code_directory = self.path.parent / "config" / "tools"
    iterdir = Path.iterdir

    def inaccessible_directory(path):
      if path == code_directory:
        raise PermissionError("cannot list managed directory")
      return iterdir(path)

    with (
      patch.object(Path, "iterdir", inaccessible_directory),
      self.assertLogs("shikigen.tools.tool_library", level="WARNING"),
    ):
      response = await self.client.put(
        f"/api/tools/{saved['data']['id']}",
        json={
          "definition": self.python("def main(): return 'committed'\n"),
          "version": saved["version"],
        },
      )
    self.assertEqual(response.status_code, 204, response.text)
    self.assertEqual(response.content, b"")
    self.assertEqual((await self.execute(saved))["data"], "committed")
    old_code = self.path.parent / saved["data"]["code_path"]
    self.assertTrue(old_code.exists())
    created = await self.client.post(
      "/api/tools",
      json={
        "name": "later_http",
        "display_name": "后续保存",
        "url": "http://localhost/",
      },
    )
    self.assertEqual(created.status_code, 201, created.text)
    self.assertEqual(set(created.json()), {"data"})
    self.assertFalse(old_code.exists())

  async def test_backend_startup_cleans_orphans_but_preserves_current_source(self):
    saved = await self.create(self.python("def main(): return 'current'\n"))
    code = self.path.parent / saved["data"]["code_path"]
    orphan = code.parent / ("00000000-0000-0000-0000-000000000000-" + "a" * 32 + ".py")
    orphan.write_text("# unused", encoding="utf-8")
    user_file = code.parent / "example.py"
    user_file.write_text("# keep", encoding="utf-8")
    runtime = assemble_runtime(
      config=load_app_config(self.path), agent=None, chat_store=self.runtime.chat_store
    )
    self.addAsyncCleanup(runtime.lifecycle.shutdown)
    app = create_app(runtime=runtime)
    async with app.router.lifespan_context(app):
      self.assertFalse(orphan.exists())
      self.assertTrue(code.exists())
      self.assertTrue(user_file.exists())
      async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
      ) as client:
        executed = await client.post(
          f"/api/tools/{saved['data']['id']}/execute", json={"inputs": {}}
        )
        self.assertEqual(executed.json()["data"]["data"], "current")

  async def test_startup_skips_cleanup_with_bad_config_and_later_write_retries(self):
    saved = await self.create(self.python("def main(): return 'current'\n"))
    code = self.path.parent / saved["data"]["code_path"]
    orphan = code.parent / ("00000000-0000-0000-0000-000000000000-" + "b" * 32 + ".py")
    orphan.write_text("# unused", encoding="utf-8")
    before = self.path.read_bytes()
    runtime = assemble_runtime(
      config=self.runtime.config, agent=None, chat_store=self.runtime.chat_store
    )
    self.addAsyncCleanup(runtime.lifecycle.shutdown)
    app = create_app(runtime=runtime)
    self.path.write_text("broken JSON", encoding="utf-8")
    with self.assertLogs("shikigen.tools.tool_library", level="WARNING"):
      async with app.router.lifespan_context(app):
        self.assertTrue(orphan.exists())
        self.assertTrue(code.exists())
        async with httpx.AsyncClient(
          transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
          self.assertEqual((await client.get("/api/tools")).status_code, 503)
          self.path.write_bytes(before)
          response = await client.post(
            "/api/mcp/connections",
            json={"display_name": "后续保存", "command": "missing-executable"},
          )
          self.assertEqual(response.status_code, 201, response.text)
          self.assertFalse(orphan.exists())
          self.assertTrue(code.exists())

  async def test_http_current_call_uses_old_auth_and_next_call_uses_new_definition(
    self,
  ):
    arrived, release = asyncio.Event(), asyncio.Event()
    requests = []

    async def service(reader, writer):
      request = await reader.readuntil(b"\r\n\r\n")
      requests.append(request.decode())
      old = b"GET /old " in request
      if old:
        arrived.set()
        await release.wait()
      body = b'"old"' if old else b'"new"'
      writer.write(
        b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
        + str(len(body)).encode()
        + b"\r\n\r\n"
        + body
      )
      await writer.drain()
      writer.close()
      await writer.wait_closed()

    server = await asyncio.start_server(service, "127.0.0.1", 0)
    self.addCleanup(server.close)
    self.addCleanup(release.set)
    origin = f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}"
    definition = {
      "kind": "http",
      "name": "remote",
      "display_name": "HTTP",
      "url": origin + "/old",
      "auth": [{"id": "token", "kind": "bearer", "value": "old-token"}],
    }
    saved = await self.create(definition)
    current_call = asyncio.create_task(self.execute(saved))
    await asyncio.wait_for(arrived.wait(), 5)
    definition.update(
      url=origin + "/new",
      auth=[{"id": "token", "kind": "bearer", "value": "new-token"}],
    )
    changed = await self.client.put(
      f"/api/tools/{saved['data']['id']}",
      json={"definition": definition, "version": saved["version"]},
    )
    self.assertEqual(changed.status_code, 204, changed.text)
    self.assertEqual((await self.execute(saved))["data"], "new")
    release.set()
    self.assertEqual((await current_call)["data"], "old")
    self.assertIn("Authorization: Bearer old-token", requests[0])
    self.assertIn("Authorization: Bearer new-token", requests[1])

  async def test_mcp_connection_change_and_delete_leave_current_call_on_old_settings(
    self,
  ):
    arrived, release = asyncio.Event(), asyncio.Event()

    async def signal(reader, writer):
      await reader.readuntil(b"\r\n\r\n")
      arrived.set()
      await release.wait()
      writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
      await writer.drain()
      writer.close()
      await writer.wait_closed()

    server = await asyncio.start_server(signal, "127.0.0.1", 0)
    self.addCleanup(server.close)
    self.addCleanup(release.set)
    origin = f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}"
    definition = {
      "display_name": "stdio",
      "command": sys.executable,
      "args": [str(Path(__file__).parent / "fixtures/mcp_stdio_server.py")],
      "env": {
        "MODE": "old",
        "MCP_FIXTURE_SIGNAL_PHASE": "tools/call",
        "MCP_FIXTURE_SIGNAL_URL": origin,
      },
    }
    created = await self.client.post("/api/mcp/connections", json=definition)
    connection_id = created.json()["data"]["id"]
    base = f"/api/mcp/connections/{connection_id}"
    discovery = (await self.client.post(base + "/discover")).json()["data"]
    imported = await self.client.post(
      base + "/imports",
      json={
        "discovery_id": discovery["discovery_id"],
        "tools": [{"remote_name": "search", "name": "search"}],
      },
    )
    self.assertEqual(imported.status_code, 200, imported.text)
    saved = (
      await self.client.get("/api/tools/" + imported.json()["data"][0]["id"])
    ).json()
    current_call = asyncio.create_task(self.execute(saved, {"query": "old"}))
    await asyncio.wait_for(arrived.wait(), 10)
    current = (await self.client.get(base)).json()
    definition["env"] = {"MODE": "new"}
    changed = await self.client.put(
      base, json={"definition": definition, "version": current["version"]}
    )
    self.assertEqual(changed.status_code, 204, changed.text)
    self.assertEqual(
      (await self.execute(saved, {"query": "new"}))["data"]["mode"], "new"
    )
    current = (await self.client.get(base)).json()
    deleted = await self.client.request(
      "DELETE", base, json={"version": current["version"]}
    )
    self.assertEqual(deleted.status_code, 204, deleted.text)
    self.assertEqual(
      (await self.execute(saved, {"query": "next"}))["error"]["code"], "not_found"
    )
    release.set()
    self.assertEqual((await current_call)["data"]["mode"], "old")
