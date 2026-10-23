"""稳定 ID 复用：公开管理/执行 API 与无需 Agent 的工具装配接口。"""

import asyncio
import json
import sys
import tempfile
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import httpx
from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool
from shikigen.app_config import load_app_config
from shikigen.persistence import ChatStore
from shikigen.runtime.composition import assemble_runtime
from shikigen.runtime.tool_library import ToolLibrary, ToolLibraryError
from shikigen.tools.executor import ToolExecutor

from app.server import create_app


class ToolConsumerTests(unittest.IsolatedAsyncioTestCase):
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
    self.library = self.runtime.tools
    app = create_app(runtime=self.runtime)
    context = app.router.lifespan_context(app)
    await context.__aenter__()
    self.addAsyncCleanup(context.__aexit__, None, None, None)
    self.client = httpx.AsyncClient(
      transport=httpx.ASGITransport(app=app), base_url="http://test"
    )
    self.addAsyncCleanup(self.client.aclose)
    self.addAsyncCleanup(self.runtime.lifecycle.shutdown)

  async def create(self, definition):
    response = await self.client.post("/api/tools", json=definition)
    self.assertEqual(response.status_code, 201, response.text)
    return response.json()["data"]["id"]

  async def test_build_by_id_preserves_complete_result_for_plain_and_tool_calls(self):
    tool_id = await self.create(
      {
        "kind": "python",
        "name": "calculate",
        "display_name": "计算",
        "source": (
          "def main(count: int):\n"
          "    print('calculated')\n"
          "    return {'total': count * 2, 'optional': None}\n"
        ),
      }
    )
    # 普通宿主只提供工具库；无需创建 Agent、Run 或聊天存储来装配/调用。
    tools = ToolLibrary(self.path)
    self.addAsyncCleanup(tools.shutdown)
    definition, _ = await tools.get_tool(tool_id)
    self.assertEqual(definition.id, tool_id)
    built = await tools.build_tools([tool_id, tool_id])
    self.assertEqual(len(built), 1)
    tool = built[0]
    self.assertIsInstance(tool, BaseTool)
    self.assertEqual(tool.name, "calculate")
    self.assertEqual(tool.metadata["tool_id"], tool_id)
    result = await tool.ainvoke({"count": 3})
    self.assertEqual(result["status"], "success")
    self.assertEqual(result["data"], {"total": 6, "optional": None})
    self.assertTrue(result["data_available"])
    self.assertIsNone(result["error"])
    self.assertGreater(result["duration_ms"], 0)
    self.assertEqual(result["details"]["stdout"].splitlines(), ["calculated"])
    self.assertEqual(result["details"]["tool_id"], tool_id)
    message = await tool.ainvoke(
      {"type": "tool_call", "id": "call-1", "name": tool.name, "args": {"count": "3"}}
    )
    self.assertIsInstance(message, ToolMessage)
    self.assertEqual(message.status, "error")
    self.assertEqual(message.artifact["error"]["code"], "input_validation")
    self.assertFalse(message.artifact["data_available"])
    self.assertEqual(message.artifact["details"]["tool_id"], tool_id)
    self.assertEqual(json.loads(message.content), message.artifact)

  async def update(self, tool_id, definition):
    saved = (await self.client.get(f"/api/tools/{tool_id}")).json()
    response = await self.client.put(
      f"/api/tools/{tool_id}",
      json={"definition": definition, "version": saved["version"]},
    )
    self.assertEqual(response.status_code, 204, response.text)

  async def test_build_rejects_missing_disabled_unsupported_and_broken_resources(self):
    payload = {
      "kind": "python",
      "name": "selected",
      "display_name": "所选工具",
      "source": "def main(): return None\n",
    }
    tool_id = await self.create(payload)

    async def rejects(ids, code, resource_id):
      with self.assertRaises(ToolLibraryError) as raised:
        await self.library.build_tools(ids)
      self.assertEqual(raised.exception.code, code)
      self.assertIn(resource_id, raised.exception.resource_ids)
      self.assertIn(resource_id, str(raised.exception))

    await rejects([tool_id, "missing-id"], "not_found", "missing-id")
    await self.update(tool_id, {**payload, "enabled": False})
    await rejects([tool_id], "disabled", tool_id)
    await self.update(tool_id, payload)
    original_executor = self.library.executor
    self.library.executor = ToolExecutor(adapters={})
    await rejects([tool_id], "unsupported_kind", tool_id)
    self.library.executor = original_executor
    definition, _ = await self.library.get_tool(tool_id)
    code = self.path.parent / definition.code_path
    code.unlink()
    await rejects([tool_id], "python_source_read", tool_id)
    self.path.write_text("{broken", encoding="utf-8")
    await rejects([tool_id], "config_read", tool_id)

  async def test_built_tool_rechecks_latest_schema_identity_and_eligibility(self):
    arrived, release = asyncio.Event(), asyncio.Event()

    async def wait_for_release(reader, writer):
      await reader.readuntil(b"\r\n\r\n")
      arrived.set()
      await release.wait()
      writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n")
      await writer.drain()
      writer.close()
      await writer.wait_closed()

    server = await asyncio.start_server(wait_for_release, "127.0.0.1", 0)
    self.addAsyncCleanup(server.wait_closed)
    self.addCleanup(server.close)
    self.addCleanup(release.set)
    url = f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}"
    original = {
      "kind": "python",
      "name": "before_rename",
      "display_name": "调用快照",
      "source": (
        "from urllib.request import urlopen\n"
        "def main(count: int):\n"
        f"    with urlopen({url!r}) as response: response.read()\n"
        "    return {'old': count}\n"
      ),
    }
    tool_id = await self.create(original)
    tool = (await self.library.build_tools([tool_id]))[0]
    in_flight = asyncio.create_task(tool.ainvoke({"count": 3}))
    await asyncio.wait_for(arrived.wait(), 10)
    changed = {
      **original,
      "name": "after_rename",
      "source": "def main(amount: int): return {'new': amount * 2}\n",
    }
    await self.update(tool_id, changed)
    current, _ = await self.library.get_tool(tool_id)
    self.assertEqual((current.id, current.name), (tool_id, "after_rename"))
    self.assertEqual(
      (await tool.ainvoke({"count": 3}))["error"]["code"], "input_validation"
    )
    self.assertEqual((await tool.ainvoke({"amount": 4}))["data"], {"new": 8})
    await self.update(tool_id, {**changed, "enabled": False})
    self.assertEqual((await tool.ainvoke({"amount": 4}))["error"]["code"], "disabled")
    manual = await self.client.post(
      f"/api/tools/{tool_id}/tests", json={"inputs": {"amount": 5}}
    )
    self.assertEqual(manual.status_code, 202, manual.text)
    saved = (await self.client.get(f"/api/tools/{tool_id}")).json()
    deleted = await self.client.request(
      "DELETE", f"/api/tools/{tool_id}", json={"version": saved["version"]}
    )
    self.assertEqual(deleted.status_code, 204, deleted.text)
    missing = await tool.ainvoke({"amount": 4})
    self.assertEqual(missing["error"]["code"], "not_found")
    self.assertEqual(missing["details"]["tool_id"], tool_id)
    release.set()
    self.assertEqual((await asyncio.wait_for(in_flight, 10))["data"], {"old": 3})

  def local_service(self):
    state = {"status": 200, "data": {}, "events": [], "authorization": []}

    class Handler(BaseHTTPRequestHandler):
      def do_GET(self):
        state["events"].append("mcp" if self.path.startswith("/mcp") else "http")
        state["authorization"].append(self.headers.get("Authorization"))
        self.send_response(state["status"] if self.path == "/" else 200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(state["data"]).encode())

      def do_POST(self):
        state["events"].append("python")
        self.send_response(204)
        self.end_headers()

      def log_message(self, *args):
        pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    Thread(target=server.serve_forever, daemon=True).start()
    self.addCleanup(server.server_close)
    self.addCleanup(server.shutdown)
    return f"http://127.0.0.1:{server.server_port}", state

  async def import_mcp(self, schema, env, remote_name="accept"):
    created = await self.client.post(
      "/api/mcp/connections",
      json={
        "display_name": "消费者对端",
        "command": sys.executable,
        "args": [str(Path(__file__).parent / "fixtures/mcp_stdio_server.py")],
        "env": {
          **env,
          "MCP_FIXTURE_TOOLS": json.dumps(
            [{"name": remote_name, "inputSchema": schema}]
          ),
        },
      },
    )
    self.assertEqual(created.status_code, 201, created.text)
    base = f"/api/mcp/connections/{created.json()['data']['id']}"
    preview = await self.client.post(base + "/discover")
    self.assertEqual(preview.status_code, 200, preview.text)
    imported = await self.client.post(
      base + "/imports",
      json={
        "discovery_id": preview.json()["data"]["discovery_id"],
        "tools": [{"remote_name": remote_name, "name": "accept_fields"}],
      },
    )
    self.assertEqual(imported.status_code, 200, imported.text)
    return imported.json()["data"][0]["id"]

  async def execute(self, tool_id, inputs):
    response = await self.client.post(
      f"/api/tools/{tool_id}/execute", json={"inputs": inputs}
    )
    self.assertEqual(response.status_code, 200, response.text)
    return response.json()["data"]

  async def test_http_python_mcp_consumers_transfer_fields_and_stop_before_bad_inputs(
    self,
  ):
    origin, state = self.local_service()
    secret = "consumer-known-secret"
    state["data"] = {
      "order": {"customer": {"name": "小明", "tags": ["a", None]}, "unit_price": 7},
      "quantities": [2, 3],
      "active": True,
      "note": None,
      "token_echo": secret,
    }
    http_id = await self.create(
      {
        "name": "fetch_order",
        "display_name": "读取订单",
        "url": origin + "/",
        "auth": [{"id": "bearer", "kind": "bearer", "value": secret}],
        # 本地输出结构是字段提示，真实返回不会按它强制转换。
        "output_schema": {"type": "object", "required": ["not_in_response"]},
      }
    )
    python_id = await self.create(
      {
        "kind": "python",
        "name": "price_order",
        "display_name": "计算订单",
        "source": (
          "from urllib.request import Request, urlopen\n"
          "def main(order: dict, quantities: list[int], active: bool,"
          " note: str | None):\n"
          f"    with urlopen(Request({origin + '/python'!r}, method='POST'))"
          " as response: response.read()\n"
          "    print('priced')\n"
          "    return {'invoice': {'customer': order['customer'],"
          " 'total': sum(quantities) * order['unit_price']},\n"
          "            'quantities': quantities, 'active': active, 'note': note}\n"
        ),
        "input_schema": {
          "type": "object",
          "properties": {
            "order": {"type": "object", "additionalProperties": True},
            "quantities": {"type": "array", "items": {"type": "integer", "minimum": 1}},
            "active": {"type": "boolean"},
            "note": {"type": ["string", "null"]},
          },
          "required": ["order", "quantities", "active", "note"],
          "additionalProperties": False,
        },
      }
    )
    mcp_id = await self.import_mcp(
      {
        "type": "object",
        "properties": {
          "invoice": {
            "type": "object",
            "properties": {
              "customer": {"type": "object", "additionalProperties": True},
              "total": {"type": "integer", "minimum": 1},
            },
            "required": ["customer", "total"],
            "additionalProperties": False,
          },
          "quantities": {"type": "array", "items": {"type": "integer"}},
          "active": {"type": "boolean"},
          "note": {"type": ["string", "null"]},
        },
        "required": ["invoice", "quantities", "active", "note"],
        "additionalProperties": False,
      },
      {
        "MCP_FIXTURE_SIGNAL_PHASE": "tools/call",
        "MCP_FIXTURE_SIGNAL_URL": origin + "/mcp",
        "API_TOKEN": secret,
        "MODE": secret,
      },
    )

    def data_of(result):
      if result["status"] != "success":
        raise RuntimeError(result["error"]["code"])
      return result["data"]

    def python_inputs(data):
      return {name: data[name] for name in ("order", "quantities", "active", "note")}

    def mcp_inputs(data):
      return {name: data[name] for name in ("invoice", "quantities", "active", "note")}

    fetched = await self.execute(http_id, {})
    self.assertEqual(
      fetched["data"]["order"]["customer"]["name"].encode("unicode_escape"),
      b"\\u5c0f\\u660e",
    )
    self.assertEqual(fetched["data"]["token_echo"], "[REDACTED]")
    self.assertEqual(state["authorization"][0], "Bearer " + secret)
    priced = await self.execute(python_id, python_inputs(data_of(fetched)))
    self.assertEqual(
      priced["data"]["invoice"]["customer"]["name"].encode("unicode_escape"),
      b"\\u5c0f\\u660e",
    )
    forwarded = mcp_inputs(data_of(priced))
    accepted = await self.execute(mcp_id, forwarded)
    self.assertEqual(accepted["status"], "success")
    self.assertEqual(
      accepted["data"]["arguments"]["invoice"]["customer"]["name"].encode(
        "unicode_escape"
      ),
      b"\\u5c0f\\u660e",
    )
    self.assertEqual(
      accepted["data"]["arguments"],
      {
        "invoice": {"customer": {"name": "小明", "tags": ["a", None]}, "total": 35},
        "quantities": [2, 3],
        "active": True,
        "note": None,
      },
    )
    self.assertEqual(state["events"], ["http", "python", "mcp"])
    self.assertEqual(accepted["data"]["mode"], "[REDACTED]")
    self.assertEqual(accepted["details"]["raw_result"]["vendor"], {"complete": True})
    self.assertEqual(accepted["details"]["raw_result"]["content"][1]["type"], "image")
    self.assertNotIn(secret, json.dumps(accepted))

    for invalid, path in (
      ({key: value for key, value in forwarded.items() if key != "invoice"}, []),
      (
        {**forwarded, "invoice": {**forwarded["invoice"], "total": "35"}},
        ["invoice", "total"],
      ),
      (
        {**forwarded, "invoice": {**forwarded["invoice"], "total": 0}},
        ["invoice", "total"],
      ),
    ):
      rejected = await self.execute(mcp_id, invalid)
      self.assertEqual(rejected["error"]["code"], "input_validation")
      self.assertEqual(rejected["details"]["path"], path)
      self.assertEqual(state["events"], ["http", "python", "mcp"])
    for quantities in (["2"], [0]):
      bad = {**data_of(fetched), "quantities": quantities}
      rejected = await self.execute(python_id, python_inputs(bad))
      self.assertEqual(rejected["error"]["code"], "input_validation")
      self.assertEqual(state["events"], ["http", "python", "mcp"])
    state["data"].pop("order")
    missing = data_of(await self.execute(http_id, {}))
    with self.assertRaises(KeyError):
      python_inputs(missing)
    self.assertEqual(state["events"], ["http", "python", "mcp", "http"])
    state["status"] = 503
    failed = await self.execute(http_id, {})
    with self.assertRaisesRegex(RuntimeError, "http_status"):
      python_inputs(data_of(failed))
    self.assertEqual(state["events"], ["http", "python", "mcp", "http", "http"])

    built_mcp = (await self.library.build_tools([mcp_id]))[0]
    message = await built_mcp.ainvoke(
      {"type": "tool_call", "id": "mcp-call", "name": built_mcp.name, "args": forwarded}
    )
    self.assertEqual(message.status, "success")
    self.assertEqual(message.artifact["data"]["arguments"], forwarded)
    self.assertEqual(
      message.artifact["details"]["raw_result"]["vendor"], {"complete": True}
    )
    self.assertNotIn(secret, json.dumps(message.model_dump()))
    self.assertEqual(json.loads(message.content), message.artifact)

  async def test_mcp_tool_error_remains_an_error_with_all_content_and_artifact(self):
    tool_id = await self.import_mcp(
      {"type": "object", "properties": {}, "additionalProperties": False},
      {},
      remote_name="fail",
    )
    tool = (await self.library.build_tools([tool_id]))[0]
    for tool_input in (
      {},
      {"type": "tool_call", "id": "failed-call", "name": tool.name, "args": {}},
    ):
      result = await tool.ainvoke(tool_input)
      if isinstance(result, ToolMessage):
        self.assertEqual(result.status, "error")
        self.assertEqual(json.loads(result.content), result.artifact)
        result = result.artifact
      self.assertEqual(result["status"], "error")
      self.assertEqual(result["error"]["code"], "mcp_tool_error")
      self.assertTrue(result["data_available"])
      self.assertEqual(len(result["data"]), 2)
      self.assertEqual(result["details"]["raw_result"]["_meta"], {"source": "fixture"})
      self.assertEqual(result["details"]["raw_result"]["vendor"], {"complete": True})

  async def test_business_parameter_names_are_not_consumed_by_langchain_injection(self):
    tool_id = await self.create(
      {
        "kind": "python",
        "name": "business_names",
        "display_name": "业务参数",
        "source": (
          "def main(config: str, run_manager: str, tool_call_id: str):\n"
          "    return [config, run_manager, tool_call_id, None]\n"
        ),
      }
    )
    tool = (await self.library.build_tools([tool_id]))[0]
    inputs = {"config": "customer", "run_manager": "owner", "tool_call_id": "business"}
    result = await tool.ainvoke(inputs)
    self.assertEqual(result["status"], "success")
    self.assertEqual(result["data"], ["customer", "owner", "business", None])
    self.assertEqual(inputs["tool_call_id"], "business")

  async def test_business_type_tool_call_is_not_a_langchain_envelope(self):
    tool_id = await self.create(
      {
        "kind": "python",
        "name": "business_type",
        "display_name": "业务类型",
        "source": "def main(type: str): return {'type': type}\n",
      }
    )
    tool = (await self.library.build_tools([tool_id]))[0]
    inputs = {"type": "tool_call"}
    direct = await self.library.execute_tool(tool_id, inputs)
    built = await tool.ainvoke(inputs, config={"tags": ["consumer"]})
    self.assertEqual((direct.status, direct.data), ("success", {"type": "tool_call"}))
    self.assertEqual(built["status"], direct.status)
    self.assertEqual(built["data"], direct.data)
    self.assertEqual(built["details"]["tool_id"], tool_id)
    actual_call = await tool.ainvoke(
      {"type": "tool_call", "id": "real-call", "name": tool.name, "args": inputs}
    )
    self.assertEqual(actual_call.status, "success")
    self.assertEqual(actual_call.artifact["data"], {"type": "tool_call"})


if __name__ == "__main__":
  unittest.main()
