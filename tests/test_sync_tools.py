"""同步脚本与异步宿主共用已保存工具的公开调用接口。"""

import asyncio
import json
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import Future, ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Event as ThreadEvent
from threading import Thread
from unittest.mock import AsyncMock, Mock, patch

from langchain_core.messages import ToolMessage
from shikigen.contracts.tool_results import ToolResult
from shikigen.tools.tool_library import ToolLibrary, open_sync_tool_library

from tests.fixtures.mcp_http_server import McpHttpServer


class SyncToolTests(unittest.TestCase):
  def setUp(self):
    directory = tempfile.TemporaryDirectory()
    self.addCleanup(directory.cleanup)
    self.path = Path(directory.name) / "config.json"
    self.path.write_text("{}", encoding="utf-8")

  def save(self, payload):
    async def save():
      library = ToolLibrary(self.path)
      try:
        definition, _ = await library.save_tool(payload)
        return definition.id
      finally:
        await library.shutdown()

    return asyncio.run(save())

  def test_sync_python_tool_preserves_result_and_tool_message(self):
    tool_id = self.save(
      {
        "kind": "python",
        "name": "calculate",
        "display_name": "同步计算",
        "source": (
          "def main(count: int):\n"
          "    print('calculated')\n"
          "    return {'total': count * 2, 'optional': None}\n"
        ),
      }
    )
    with open_sync_tool_library(self.path) as library:
      tool = library.build_tools([tool_id, tool_id])[0]
      result = tool.invoke({"count": 3})
      self.assertEqual(result["status"], "success")
      self.assertEqual(result["data"], {"total": 6, "optional": None})
      self.assertTrue(result["data_available"])
      self.assertEqual(result["details"]["tool_id"], tool_id)
      self.assertEqual(result["details"]["stdout"].splitlines(), ["calculated"])
      message = tool.invoke(
        {"type": "tool_call", "id": "call-1", "name": tool.name, "args": {"count": "3"}}
      )
      self.assertIsInstance(message, ToolMessage)
      self.assertEqual(message.status, "error")
      self.assertEqual(message.artifact["error"]["code"], "input_validation")
      self.assertEqual(json.loads(message.content), message.artifact)
      direct = library.execute_tool(tool_id, {"count": 4})
      self.assertEqual(direct.data, {"total": 8, "optional": None})

  def test_closed_context_rejects_both_call_modes_and_facade(self):
    tool_id = self.save(
      {
        "kind": "python",
        "name": "closed_tool",
        "display_name": "已关闭",
        "source": "def main(): return None\n",
      }
    )
    with open_sync_tool_library(self.path) as library:
      tool = library.build_tools([tool_id])[0]
      self.assertEqual(asyncio.run(tool.ainvoke({}))["status"], "success")
    with self.assertRaisesRegex(RuntimeError, "closed"):
      tool.invoke({})
    with self.assertRaisesRegex(RuntimeError, "closed"):
      asyncio.run(tool.ainvoke({}))
    with self.assertRaisesRegex(RuntimeError, "closed"):
      library.build_tools([tool_id])

  def test_sync_inputs_preserve_business_names_and_tool_call_type(self):
    tool_id = self.save(
      {
        "kind": "python",
        "name": "business_inputs",
        "display_name": "业务参数",
        "source": (
          "def main(type: str, config: str = 'default', "
          "run_manager: str = 'manager'):\n"
          "    return {'type': type, 'config': config, 'run_manager': run_manager}\n"
        ),
      }
    )
    with open_sync_tool_library(self.path) as library:
      tool = library.build_tools([tool_id])[0]
      inputs = {"type": "tool_call", "config": "business", "run_manager": "owner"}
      result = tool.invoke(inputs, config={"tags": ["sync-consumer"]})
      self.assertEqual(result["data"], inputs)
      message = tool.invoke(
        {"type": "tool_call", "id": "real-call", "name": tool.name, "args": inputs}
      )
      self.assertEqual(message.status, "success")
      self.assertEqual(message.artifact["data"], inputs)
      with ThreadPoolExecutor(max_workers=2) as pool:
        calls = [pool.submit(tool.invoke, {"type": "plain"}) for _ in range(2)]
        for call in calls:
          self.assertEqual(call.result()["data"]["type"], "plain")

  def test_sync_http_keeps_null_and_redacts_known_auth_values(self):
    secret = "sync-known-secret"
    requests = []

    class Handler(BaseHTTPRequestHandler):
      def do_GET(self):
        requests.append(self.headers.get("Authorization"))
        body = json.dumps({"echo": secret, "optional": None}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

      def log_message(self, *args):
        pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def close():
      server.shutdown()
      server.server_close()
      thread.join()

    self.addCleanup(close)
    tool_id = self.save(
      {
        "kind": "http",
        "name": "fetch",
        "display_name": "同步 HTTP",
        "url": f"http://127.0.0.1:{server.server_port}",
        "auth": [{"id": "bearer", "kind": "bearer", "value": secret}],
      }
    )
    with open_sync_tool_library(self.path) as library:
      result = library.build_tools([tool_id])[0].invoke({})
    self.assertEqual(result["status"], "success")
    self.assertEqual(result["data"], {"echo": "[REDACTED]", "optional": None})
    self.assertNotIn(secret, json.dumps(result))
    self.assertEqual(requests, ["Bearer " + secret])

  def test_sync_mcp_transports_preserve_complete_messages_and_close_sessions(self):
    server = McpHttpServer()
    self.addCleanup(server.close)

    async def import_tools(settings):
      library = ToolLibrary(self.path)
      try:
        connection_id = await library.save_mcp_connection(
          {"display_name": "同步 MCP", **settings}
        )
        discovery = await library.inspect_mcp_connection(connection_id, discover=True)
        self.assertEqual(discovery["status"], "success", discovery)
        imported = await library.import_mcp_tools(
          connection_id,
          discovery["discovery_id"],
          [
            {"remote_name": name, "name": settings["transport"] + "_" + name}
            for name in ("search", "fail")
          ],
        )
        return [item["id"] for item in imported]
      finally:
        await library.shutdown()

    for settings in (
      {
        "transport": "stdio",
        "command": sys.executable,
        "args": [str(Path(__file__).parent / "fixtures/mcp_stdio_server.py")],
      },
      {"transport": "streamable_http", "url": server.url},
    ):
      with self.subTest(transport=settings["transport"]):
        ids = asyncio.run(import_tools(settings))
        with open_sync_tool_library(self.path) as library:
          tool, failed_tool = library.build_tools(ids)
          message = tool.invoke(
            {
              "type": "tool_call",
              "id": "mcp-call",
              "name": tool.name,
              "args": {"query": "中文"},
            }
          )
          self.assertEqual(message.status, "success")
          self.assertEqual(message.artifact["data"]["arguments"], {"query": "中文"})
          raw = message.artifact["details"]["raw_result"]
          self.assertEqual(raw["vendor"], {"complete": True})
          self.assertEqual(raw["content"][1]["type"], "image")
          self.assertEqual(json.loads(message.content), message.artifact)
          failure = failed_tool.invoke({"query": "failure"})
          self.assertEqual(failure["error"]["code"], "mcp_tool_error")
          self.assertTrue(failure["data_available"])
        self.assertEqual(server.sessions, set())

  def test_sync_timeout_reaps_python_working_directory(self):
    state = self.path.parent / "python-state.json"
    tool_id = self.save(
      {
        "kind": "python",
        "name": "timeout_tool",
        "display_name": "同步超时",
        "timeout_seconds": 1,
        "source": (
          "import json, os, time\n"
          "def main():\n"
          f"    with open({str(state)!r}, 'w') as f:\n"
          "        json.dump({'cwd': os.getcwd()}, f)\n"
          "    time.sleep(60)\n"
        ),
      }
    )
    with open_sync_tool_library(self.path) as library:
      result = library.execute_tool(tool_id, {})
    self.assertEqual(result.status, "timeout")
    self.assertIsNotNone(result.details["exit_code"])
    self.assertFalse(Path(json.loads(state.read_text())["cwd"]).exists())

  def test_context_exit_cancels_inflight_mcp_and_releases_remote_session(self):
    server = McpHttpServer()
    self.addCleanup(server.close)

    async def import_tool():
      library = ToolLibrary(self.path)
      try:
        connection_id = await library.save_mcp_connection(
          {
            "transport": "streamable_http",
            "display_name": "关闭 MCP",
            "url": server.url,
          }
        )
        discovery = await library.inspect_mcp_connection(connection_id, discover=True)
        imported = await library.import_mcp_tools(
          connection_id,
          discovery["discovery_id"],
          [{"remote_name": "slow", "name": "inflight_mcp"}],
        )
        return imported[0]["id"]
      finally:
        await library.shutdown()

    tool_id = asyncio.run(import_tool())
    with ThreadPoolExecutor(max_workers=1) as pool:
      with open_sync_tool_library(self.path) as library:
        tool = library.build_tools([tool_id])[0]
        call = pool.submit(tool.invoke, {"query": "block"})
        self.assertTrue(server.slow_started.wait(5))
      result = call.result(timeout=5)
    self.assertEqual(result["status"], "cancelled")
    self.assertEqual(server.calls, 1)
    self.assertEqual(server.sessions, set())
    self.assertTrue(any(request["method"] == "DELETE" for request in server.requests))

  def test_keyboard_interrupt_cancels_call_and_waits_for_python_cleanup(self):
    state = self.path.parent / "interrupted-python.json"
    tool_id = self.save(
      {
        "kind": "python",
        "name": "interrupted",
        "display_name": "同步中断",
        "source": (
          "import json, os, time\n"
          "def main():\n"
          f"    with open({str(state)!r}, 'w') as f:\n"
          "        json.dump({'cwd': os.getcwd()}, f)\n"
          "    time.sleep(3)\n"
        ),
      }
    )
    script = self.path.parent / "interrupt.py"
    script.write_text(
      "import _thread, json, time\n"
      "from pathlib import Path\n"
      "from threading import Thread\n"
      "from shikigen.tools.tool_library import open_sync_tool_library\n"
      f"state = Path({str(state)!r})\n"
      "interrupted = []\n"
      "def interrupt():\n"
      "    deadline = time.monotonic() + 8\n"
      "    while not state.exists():\n"
      "        if time.monotonic() >= deadline: return\n"
      "        time.sleep(0.01)\n"
      "    interrupted.append(time.monotonic())\n"
      "    _thread.interrupt_main()\n"
      "Thread(target=interrupt, daemon=True).start()\n"
      "try:\n"
      f"    with open_sync_tool_library(Path({str(self.path)!r})) as library:\n"
      f"        library.execute_tool({tool_id!r}, {{}})\n"
      "except KeyboardInterrupt:\n"
      "    assert time.monotonic() - interrupted[0] < 1.5, 'interrupt was delayed'\n"
      "    assert not Path(json.loads(state.read_text())['cwd']).exists()\n"
      "    print('interrupted and cleaned')\n"
      "else:\n"
      "    raise AssertionError('expected KeyboardInterrupt')\n",
      encoding="utf-8",
    )
    result = subprocess.run(
      [sys.executable, str(script)], capture_output=True, text=True, timeout=15
    )
    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertIn("interrupted and cleaned", result.stdout)


class AsyncHostToolTests(unittest.IsolatedAsyncioTestCase):
  async def asyncSetUp(self):
    directory = tempfile.TemporaryDirectory()
    self.addCleanup(directory.cleanup)
    self.path = Path(directory.name) / "config.json"
    self.path.write_text("{}", encoding="utf-8")
    self.library = ToolLibrary(self.path)
    self.addAsyncCleanup(self.library.shutdown)

  async def test_shutdown_rejects_saved_and_draft_tests(self):
    payload = {
      "kind": "http",
      "name": "closed_test",
      "display_name": "关闭后的测试",
      "url": "http://localhost/",
    }
    definition, _ = await self.library.save_tool(payload)
    adapter = Mock(execute=AsyncMock(return_value=ToolResult(status="success")))
    self.library.executor.adapters["http"] = adapter
    await self.library.shutdown()

    for mode in ("saved", "draft"):
      with self.subTest(mode=mode):
        with self.assertRaisesRegex(RuntimeError, "closed"):
          if mode == "saved":
            await self.library.start_test(definition.id, {})
          else:
            await self.library.start_draft_test(payload, {}, tool_id=definition.id)
    await self.library.shutdown()
    await asyncio.sleep(0)
    adapter.execute.assert_not_awaited()

  async def test_shutdown_rejects_tests_still_loading_configuration(self):
    payload = {
      "kind": "http",
      "name": "preparing_test",
      "display_name": "准备中的测试",
      "url": "http://localhost/",
    }
    definition, _ = await self.library.save_tool(payload)

    for mode in ("saved", "draft"):
      with self.subTest(mode=mode):
        library = ToolLibrary(self.path)
        adapter = Mock(execute=AsyncMock(return_value=ToolResult(status="success")))
        library.executor.adapters["http"] = adapter
        reading, release = asyncio.Event(), ThreadEvent()
        loop = asyncio.get_running_loop()
        read = library._read

        def blocked_read(loop=loop, reading=reading, release=release, read=read):
          loop.call_soon_threadsafe(reading.set)
          if not release.wait(5):
            raise TimeoutError("Configuration read was not released")
          return read()

        with patch.object(library, "_read", blocked_read):
          operation = (
            library.start_test(definition.id, {})
            if mode == "saved"
            else library.start_draft_test(payload, {}, tool_id=definition.id)
          )
          preparing = asyncio.create_task(operation)
          try:
            await asyncio.wait_for(reading.wait(), 5)
            await library.shutdown()
            release.set()
            with self.assertRaisesRegex(RuntimeError, "closed"):
              await asyncio.wait_for(preparing, 5)
            adapter.execute.assert_not_awaited()
          finally:
            release.set()
            await asyncio.gather(preparing, return_exceptions=True)
            await library.shutdown()

  async def test_repeated_shutdown_cancellation_preserves_all_cleanup(self):
    started, cleaning, cleaned = (asyncio.Queue() for _ in range(3))
    release = asyncio.Event()

    class BlockingAdapter:
      async def execute(self, execution, inputs, *, context):
        started.put_nowait(None)
        try:
          await asyncio.Event().wait()
        finally:
          cleaning.put_nowait(None)
          await release.wait()
          cleaned.put_nowait(None)
        return ToolResult(status="success")

    self.library.executor.adapters["http"] = BlockingAdapter()
    definition, _ = await self.library.save_tool(
      {
        "kind": "http",
        "name": "shutdown_cleanup",
        "display_name": "关闭时等待清理",
        "url": "http://localhost/",
      }
    )
    execution = asyncio.create_task(self.library.execute_tool(definition.id, {}))
    test = await self.library.start_test(definition.id, {})
    closing = observer = None
    try:
      for _ in range(2):
        await asyncio.wait_for(started.get(), 5)
      closing = asyncio.create_task(self.library.shutdown())
      observer = asyncio.create_task(self.library.shutdown())
      for _ in range(2):
        await asyncio.wait_for(cleaning.get(), 5)

      closing.cancel()
      await asyncio.sleep(0)
      closing.cancel()
      await asyncio.sleep(0)
      self.assertFalse(closing.done())
      self.assertFalse(observer.done())
      self.assertTrue(cleaned.empty())

      release.set()
      with self.assertRaises(asyncio.CancelledError):
        await asyncio.wait_for(closing, 5)
      await asyncio.wait_for(observer, 5)
      self.assertEqual(cleaned.qsize(), 2)
      self.assertEqual((await execution).status, "cancelled")
      self.assertEqual(self.library.get_test(test["test_id"])["status"], "cancelled")
      await self.library.shutdown()
    finally:
      release.set()
      await asyncio.gather(
        *[task for task in (execution, closing, observer) if task is not None],
        return_exceptions=True,
      )

  async def test_async_host_supports_worker_sync_and_foreign_loop_async_calls(self):
    definition, _ = await self.library.save_tool(
      {
        "kind": "python",
        "name": "mixed",
        "display_name": "混合调用",
        "source": "def main(count: int): return count * 2\n",
      }
    )
    tool = (await self.library.build_tools([definition.id]))[0]
    with self.assertRaisesRegex(RuntimeError, "ainvoke"):
      tool.invoke({"count": 1})
    results = await asyncio.gather(
      tool.ainvoke({"count": 2}),
      asyncio.to_thread(tool.invoke, {"count": 3}),
      asyncio.to_thread(lambda: asyncio.run(tool.ainvoke({"count": 4}))),
    )
    self.assertEqual([result["data"] for result in results], [4, 6, 8])

  async def test_sync_call_keeps_snapshot_and_next_calls_read_latest_definition(self):
    arrived, release = asyncio.Event(), asyncio.Event()

    async def blocked(reader, writer):
      try:
        await reader.readuntil(b"\r\n\r\n")
        arrived.set()
        await release.wait()
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n")
        await writer.drain()
      finally:
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(blocked, "127.0.0.1", 0)
    self.addAsyncCleanup(server.wait_closed)
    self.addCleanup(server.close)
    self.addCleanup(release.set)
    url = f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}"
    payload = {
      "kind": "python",
      "name": "before_rename",
      "display_name": "同步调用快照",
      "source": (
        "from urllib.request import urlopen\n"
        "def main(count: int):\n"
        f"    with urlopen({url!r}) as response: response.read()\n"
        "    return {'old': count}\n"
      ),
    }
    definition, _ = await self.library.save_tool(payload)
    tool = (await self.library.build_tools([definition.id]))[0]
    current_call = asyncio.create_task(asyncio.to_thread(tool.invoke, {"count": 3}))
    await asyncio.wait_for(arrived.wait(), 5)
    changed = {
      **payload,
      "name": "after_rename",
      "source": "def main(amount: int): return {'new': amount * 2}\n",
    }
    _, version = await self.library.get_tool(definition.id)
    updated, _ = await self.library.save_tool(
      changed, tool_id=definition.id, version=version
    )
    self.assertEqual(updated.id, definition.id)
    invalid = await asyncio.to_thread(tool.invoke, {"count": 3})
    self.assertEqual(invalid["error"]["code"], "input_validation")
    self.assertEqual(
      (await asyncio.to_thread(tool.invoke, {"amount": 4}))["data"], {"new": 8}
    )
    _, version = await self.library.get_tool(definition.id)
    await self.library.save_tool(
      {**changed, "enabled": False}, tool_id=definition.id, version=version
    )
    disabled = await asyncio.to_thread(tool.invoke, {"amount": 4})
    self.assertEqual(disabled["error"]["code"], "disabled")
    _, version = await self.library.get_tool(definition.id)
    await self.library.delete_tool(definition.id, version)
    missing = await asyncio.to_thread(tool.invoke, {"amount": 4})
    self.assertEqual(missing["error"]["code"], "not_found")
    release.set()
    self.assertEqual((await asyncio.wait_for(current_call, 5))["data"], {"old": 3})

  async def test_repeated_foreign_loop_cancellation_waits_for_adapter_cleanup(self):
    started, cleaning, release, cleaned = (asyncio.Event() for _ in range(4))
    self.addCleanup(release.set)

    class BlockingAdapter:
      async def execute(self, execution, inputs, *, context):
        started.set()
        try:
          await asyncio.Event().wait()
        finally:
          cleaning.set()
          await release.wait()
          cleaned.set()
        return ToolResult(status="success")

    self.library.executor.adapters["http"] = BlockingAdapter()
    definition, _ = await self.library.save_tool(
      {
        "kind": "http",
        "name": "cleanup",
        "display_name": "等待清理",
        "url": "http://localhost/",
      }
    )
    tool = (await self.library.build_tools([definition.id]))[0]
    ready = Future()

    async def foreign_call():
      caller = asyncio.create_task(tool.ainvoke({}))
      ready.set_result((asyncio.get_running_loop(), caller))
      return await caller

    worker = asyncio.create_task(asyncio.to_thread(lambda: asyncio.run(foreign_call())))
    foreign_loop, caller = await asyncio.wrap_future(ready)
    await asyncio.wait_for(started.wait(), 5)
    foreign_loop.call_soon_threadsafe(caller.cancel)
    await asyncio.wait_for(cleaning.wait(), 5)
    foreign_loop.call_soon_threadsafe(caller.cancel)
    closing = asyncio.create_task(self.library.shutdown())
    await asyncio.sleep(0)
    self.assertFalse(worker.done())
    self.assertFalse(closing.done())
    release.set()
    with self.assertRaises(asyncio.CancelledError):
      await asyncio.wait_for(worker, 5)
    await asyncio.wait_for(closing, 5)
    self.assertTrue(cleaned.is_set())

  async def test_shutdown_cancels_sync_and_async_calls_and_closes_connections(self):
    arrived, closed = asyncio.Queue(), asyncio.Queue()

    async def blocked(reader, writer):
      try:
        await reader.readuntil(b"\r\n\r\n")
        arrived.put_nowait(None)
        await reader.read()
      finally:
        writer.close()
        await writer.wait_closed()
        closed.put_nowait(None)

    server = await asyncio.start_server(blocked, "127.0.0.1", 0)
    self.addAsyncCleanup(server.wait_closed)
    self.addCleanup(server.close)
    definition, _ = await self.library.save_tool(
      {
        "kind": "http",
        "name": "blocked",
        "display_name": "关闭调用",
        "url": f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}",
      }
    )
    tool = (await self.library.build_tools([definition.id]))[0]
    sync_call = asyncio.create_task(asyncio.to_thread(tool.invoke, {}))
    async_call = asyncio.create_task(tool.ainvoke({}))
    for _ in range(2):
      await asyncio.wait_for(arrived.get(), 5)
    await self.library.shutdown()
    for call in (sync_call, async_call):
      result = await asyncio.wait_for(asyncio.shield(call), 1)
      self.assertEqual(result["status"], "cancelled")
    for _ in range(2):
      await asyncio.wait_for(closed.get(), 1)
    with self.assertRaisesRegex(RuntimeError, "closed"):
      await self.library.execute_tool(definition.id, {})


if __name__ == "__main__":
  unittest.main()
