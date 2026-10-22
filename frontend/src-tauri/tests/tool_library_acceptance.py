"""第一个 HTTP 工具：真实 Tauri 页面、公开 API 和本地 HTTP 服务。"""

import base64
import json
import sys
import unittest
from functools import partial
from http.server import (
  BaseHTTPRequestHandler,
  SimpleHTTPRequestHandler,
  ThreadingHTTPServer,
)
from threading import Thread

from client_acceptance import ClientAcceptance
from window_acceptance import REPO, WindowAcceptance, wait_until

from tests.fixtures.mcp_http_server import McpHttpServer


class ToolLibraryAcceptance(WindowAcceptance):
  artifact_root = REPO / ".scratch/tools-workflow/verification/native"
  body = ClientAcceptance.body
  click = ClientAcceptance.click

  @classmethod
  def setUpClass(cls):
    cls.static_server = ThreadingHTTPServer(
      ("127.0.0.1", 0),
      partial(SimpleHTTPRequestHandler, directory=str(REPO / "frontend/dist")),
    )
    Thread(target=cls.static_server.serve_forever, daemon=True).start()
    cls.addClassCleanup(cls.static_server.server_close)
    cls.addClassCleanup(cls.static_server.shutdown)
    cls.static_origin = f"http://127.0.0.1:{cls.static_server.server_port}"

  def setUp(self):
    super().setUp()
    self.fixture.env["SHIKIGEN_DESKTOP_DEV_ORIGIN"] = self.static_origin
    self.fixture.env["SHIKIGEN_ACCEPTANCE_DEV_ORIGIN"] = self.static_origin

  def tearDown(self):
    if any(
      case is self
      for case, _ in self._outcome.result.failures + self._outcome.result.errors
    ):
      if self.ws is not None:
        self.record(body=self.body())
        self.screenshot()

  def fill(self, field, value):
    self.evaluate(f"document.getElementById({json.dumps(field)}).focus()")
    self.call("Input.insertText", text=value)

  def press_key(self, key, code, virtual_key, modifiers=0):
    self.call(
      "Input.dispatchKeyEvent",
      type="keyDown",
      key=key,
      code=code,
      windowsVirtualKeyCode=virtual_key,
      modifiers=modifiers,
    )
    self.call("Input.dispatchKeyEvent", type="keyUp", key=key, code=code, modifiers=0)

  def replace(self, field, value):
    editable = self.evaluate(
      f"document.getElementById({json.dumps(field)}).isContentEditable"
    )
    if editable:
      self.evaluate(f"document.getElementById({json.dumps(field)}).focus()")
      self.press_key("a", "KeyA", 65, 2)
    else:
      self.evaluate(f"document.getElementById({json.dumps(field)}).select()")
    self.fill(field, value)

  def test_openapi_upload_paste_configure_edit_and_execute(self):
    requests = []

    class Handler(BaseHTTPRequestHandler):
      def do_GET(self):
        requests.append(self.path)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"path": self.path}).encode())

      def log_message(self, *args):
        pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    Thread(target=server.serve_forever, daemon=True).start()
    self.addCleanup(server.server_close)
    self.addCleanup(server.shutdown)
    origin = f"http://127.0.0.1:{server.server_port}"
    host = self.launch()
    self.connect()
    base = self.state("ready")["base_url"]
    wait_until(lambda: "新建会话开始对话" in self.body())
    self.evaluate("document.querySelector('[aria-label=工具]').click()")
    wait_until(lambda: "工具库为空" in self.body())
    self.evaluate("document.querySelector('[aria-label=选择接入类型]').click()")
    self.click("导入 OpenAPI 文档")
    wait_until(lambda: "OpenAPI 文档" in self.body())
    document = {
      "openapi": "3.1.0",
      "info": {"title": "订单 API", "version": "1"},
      "servers": [{"url": "/relative"}],
      "paths": {
        "/orders": {
          "get": {
            "operationId": "list-orders",
            "summary": "订单查询",
            "description": "查找订单",
            "parameters": [
              {
                "name": "message",
                "in": "query",
                "required": True,
                "schema": {"type": "string", "description": "原始查询参数"},
              }
            ],
            "responses": {
              "200": {
                "description": "成功",
                "content": {
                  "application/json": {
                    "schema": {
                      "type": "object",
                      "properties": {"path": {"type": "string"}},
                    }
                  }
                },
              }
            },
          }
        }
      },
    }
    file_path = self.artifacts / "openapi.json"
    file_path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    root = self.call("DOM.getDocument")["root"]["nodeId"]
    node = self.call("DOM.querySelector", nodeId=root, selector="input[type=file]")[
      "nodeId"
    ]
    self.call("DOM.setFileInputFiles", files=[str(file_path)], nodeId=node)
    wait_until(lambda: "已读取 openapi.json" in self.body())
    self.click("解析文档")
    wait_until(
      lambda: (
        "选择 GET /orders"
        in self.evaluate(
          "[...document.querySelectorAll('input[aria-label]')]"
          ".map(el => el.ariaLabel).join('|')"
        )
      )
    )
    self.evaluate("document.querySelector('[aria-label=\"选择 GET /orders\"]').click()")
    self.assertEqual(
      self.evaluate("document.getElementById('tool-config_name').value"), "list_orders"
    )
    self.assertIn("需要补配置", self.body())
    self.replace("tool-config_url", origin + "/orders")
    self.assertEqual(requests, [])
    self.assertEqual(self.client.get(base + "/api/tools").json()["data"], [])
    for width, height in ((1440, 900), (390, 844)):
      self.call(
        "Emulation.setDeviceMetricsOverride",
        width=width,
        height=height,
        deviceScaleFactor=1,
        mobile=False,
      )
      wait_until(lambda width=width: self.evaluate("window.innerWidth") == width)
      self.assertFalse(
        self.evaluate("document.documentElement.scrollWidth > window.innerWidth")
      )
      self.assertTrue(
        self.evaluate("""(() => {
        const button = document.querySelector('.openapi-toolbar button:last-child');
        const rect = button.getBoundingClientRect();
        return rect.width > 0 && rect.left >= 0 && rect.right <= innerWidth;
      })()""")
      )
      self.evaluate("document.querySelector('.tool-detail-view').scrollTop = 0")
      screenshot = self.call("Page.captureScreenshot", format="png")["data"]
      (self.artifacts / f"openapi-preview-{width}.png").write_bytes(
        base64.b64decode(screenshot)
      )
      if width == 1440:
        layout = self.evaluate("""(() => {
          const rect = selector => document.querySelector(selector)
            .getBoundingClientRect();
          const columns = document.querySelector('.tool-editor-layout').children;
          return {rail:rect('.workspace > .navigation').width,
            sidebar:rect('.tool-library-sidebar').width,
            toolbar:rect('.tool-detail-toolbar').height,
            ratio:columns[0].getBoundingClientRect().width
              / columns[1].getBoundingClientRect().width};
        })()""")
        self.assertAlmostEqual(layout["rail"], 64, delta=1)
        self.assertAlmostEqual(layout["sidebar"], 256, delta=1)
        self.assertAlmostEqual(layout["toolbar"], 48, delta=1)
        self.assertAlmostEqual(layout["ratio"], 7 / 5, delta=0.02)
    self.call("Emulation.clearDeviceMetricsOverride")
    self.click("保存所选工具")
    wait_until(lambda: "可打开详情编辑和测试" in self.body())
    first = self.client.get(base + "/api/tools").json()["data"][0]
    self.assertEqual(first["kind"], "http")
    self.assertEqual(requests, [])
    self.click("编辑工具 订单查询")
    wait_until(lambda: "快速测试调试" in self.body())
    self.replace("tool-config_display_name", "订单查询编辑")
    self.click("保存工具")
    wait_until(lambda: "工具已保存" in self.body())
    edited = self.client.get(base + f"/api/tools/{first['id']}").json()["data"]
    self.assertEqual(edited["display_name"], "订单查询编辑")
    self.fill("tool-input_query_message", "hello")
    self.click("执行测试")
    wait_until(lambda: "测试成功" in self.body())
    self.assertEqual(requests, ["/orders?message=hello"])
    self.assertIn("OpenAPI 原始来源", self.body())
    self.evaluate("document.querySelector('[aria-label=选择接入类型]').click()")
    self.click("导入 OpenAPI 文档")
    wait_until(lambda: "导入文档" in self.body())
    yaml_document = """openapi: 3.0.3
info: {title: 订单 API, version: '1'}
servers:
  - url: ORIGIN
paths:
  /orders:
    get:
      operationId: list-orders
      summary: 再次导入
      description: 创建新工具
""".replace("ORIGIN", origin)
    self.fill("openapi-document", yaml_document)
    self.click("解析文档")
    wait_until(
      lambda: self.evaluate(
        "Boolean(document.querySelector('[aria-label=\"选择 GET /orders\"]'))"
      )
    )
    self.evaluate("document.querySelector('[aria-label=\"选择 GET /orders\"]').click()")
    self.assertEqual(
      self.evaluate("document.getElementById('tool-config_name').value"),
      "list_orders_2",
    )
    self.click("保存所选工具")
    wait_until(lambda: "可打开详情编辑和测试" in self.body())
    final = self.client.get(base + "/api/tools").json()["data"]
    self.assertEqual(len(final), 2)
    self.assertEqual(final[0], edited)
    self.assertNotEqual(final[0]["id"], final[1]["id"])
    self.assertEqual(requests, ["/orders?message=hello"])
    self.record(tools=final, requests=requests)
    self.quit(host)
    self.assertEqual(host.wait(timeout=10), 0)

  def test_mcp_stdio_discover_select_call_and_source_navigation(self):
    host = self.launch()
    self.connect()
    base = self.state("ready")["base_url"]
    wait_until(lambda: "新建会话开始对话" in self.body())
    self.evaluate("document.querySelector('[aria-label=工具]').click()")
    wait_until(lambda: "工具库为空" in self.body())
    self.evaluate("document.querySelector('[aria-label=选择接入类型]').click()")
    self.click("接入 MCP 服务")
    wait_until(lambda: "暂无 MCP 连接" in self.body())
    self.evaluate("document.querySelector('[aria-label=\"接入 MCP 服务\"]').click()")
    self.evaluate("document.querySelector('[aria-label=\"新建 stdio 连接\"]').click()")
    wait_until(
      lambda: self.evaluate("Boolean(document.getElementById('mcp-config_command'))")
    )
    self.fill("mcp-config_display_name", "本地 MCP 验收")
    self.fill("mcp-config_command", sys.executable)
    self.replace(
      "mcp-config_args", json.dumps([str(REPO / "tests/fixtures/mcp_stdio_server.py")])
    )
    self.click("保存连接")
    wait_until(lambda: "连接已保存" in self.body())
    wait_until(
      lambda: self.evaluate(
        "[...document.querySelectorAll('[aria-label=\"MCP 服务操作\"] button')]"
        ".some(button => button.textContent === '测试连接' && !button.disabled)"
      )
    )
    self.click("测试连接")
    wait_until(lambda: "连接测试成功" in self.body())
    self.assertEqual(self.client.get(base + "/api/tools").json()["data"], [])
    self.click("发现工具")
    wait_until(lambda: "发现工具预览" in self.body())
    for name in ("search", "blocks"):
      self.evaluate(f"document.querySelector('[aria-label=\"选择 {name}\"]').click()")
    self.click("导入所选工具")
    wait_until(lambda: "所选工具已入库" in self.body())
    tools = self.client.get(base + "/api/tools").json()["data"]
    self.assertEqual({tool["remote_name"] for tool in tools}, {"search", "blocks"})
    selected = next(tool for tool in tools if tool["remote_name"] == "search")
    wait_until(
      lambda: self.evaluate(
        "Boolean(document.querySelector("
        "'[aria-label=\"打开工具 search\"]:not([disabled])'))"
      )
    )
    for width, height in ((1440, 900), (390, 844)):
      self.call(
        "Emulation.setDeviceMetricsOverride",
        width=width,
        height=height,
        deviceScaleFactor=1,
        mobile=False,
      )
      wait_until(lambda width=width: self.evaluate("window.innerWidth") == width)
      self.assertFalse(
        self.evaluate("document.documentElement.scrollWidth > window.innerWidth")
      )
      for text in ("测试连接", "发现工具", "保存连接"):
        self.assertTrue(
          self.evaluate(
            "[...document.querySelectorAll('button')].some(button => "
            f"button.textContent === {json.dumps(text)} && "
            "button.getBoundingClientRect().width > 0)"
          )
        )
      data = self.call("Page.captureScreenshot", format="png")["data"]
      (self.artifacts / f"mcp-services-{width}.png").write_bytes(base64.b64decode(data))
    self.call(
      "Emulation.setDeviceMetricsOverride",
      width=1440,
      height=900,
      deviceScaleFactor=1,
      mobile=False,
    )
    self.evaluate("document.querySelector('[aria-label=\"打开工具 search\"]').click()")
    wait_until(
      lambda: self.evaluate("Boolean(document.getElementById('tool-input_query'))")
    )
    self.assertTrue(
      self.evaluate("document.getElementById('tool-config_connection_id').readOnly")
    )
    self.assertTrue(
      self.evaluate("document.getElementById('tool-config_input_schema').disabled")
    )
    self.fill("tool-input_query", "native MCP")
    self.click("执行测试")
    wait_until(lambda: "测试成功" in self.body())
    self.assertIn('"query": "native MCP"', self.body())
    self.evaluate(
      "[...document.querySelectorAll('summary')].find(item => "
      "item.textContent === 'MCP 原始返回与来源').click()"
    )
    self.assertIn('"vendor"', self.body())
    self.assertIn('"complete": true', self.body())
    self.assertEqual(len(self.client.get(base + "/api/tools").json()["data"]), 2)
    for width, height in ((1440, 900), (390, 844)):
      self.call(
        "Emulation.setDeviceMetricsOverride",
        width=width,
        height=height,
        deviceScaleFactor=1,
        mobile=False,
      )
      wait_until(lambda width=width: self.evaluate("window.innerWidth") == width)
      self.assertFalse(
        self.evaluate("document.documentElement.scrollWidth > window.innerWidth")
      )
      data = self.call("Page.captureScreenshot", format="png")["data"]
      (self.artifacts / f"mcp-tool-{width}.png").write_bytes(base64.b64decode(data))
    self.evaluate(
      "document.querySelector('[aria-label=\"打开所属 MCP 服务\"]').click()"
    )
    wait_until(
      lambda: self.evaluate("Boolean(document.getElementById('mcp-config_command'))")
    )
    self.assertEqual(
      self.evaluate("document.getElementById('mcp-config_command').value"),
      sys.executable,
    )
    self.assertEqual(
      self.client.get(base + f"/api/tools/{selected['id']}").json()["data"]["id"],
      selected["id"],
    )
    # 修改连接只保存连接草稿；来源差异须重新发现并明确选择。
    changed = {
      "name": "search",
      "description": "远端已更新",
      "inputSchema": {
        "type": "object",
        "properties": {"term": {"type": "string"}},
        "required": ["term"],
      },
    }
    self.replace(
      "mcp-config_env",
      json.dumps(
        {"MCP_FIXTURE_TOOLS": json.dumps([changed, {**changed, "name": "renamed"}])}
      ),
    )
    self.evaluate(
      "document.querySelector('[aria-label=\"查看工具 本地 search\"]').click()"
    )
    wait_until(lambda: "未保存的连接修改" in self.body())
    self.click("继续编辑")
    self.click("保存连接")
    wait_until(lambda: "请重新发现核对来源结构" in self.body())
    self.assertEqual(
      self.client.get(base + f"/api/tools/{selected['id']}").json()["data"][
        "input_schema"
      ],
      selected["input_schema"],
    )
    wait_until(
      lambda: self.evaluate(
        "!document.querySelector('[aria-label=\"删除连接\"]').disabled"
      )
    )
    self.click("发现工具")
    wait_until(lambda: "来源变化" in self.body() and "本次未发现" in self.body())
    self.assertIsNone(
      self.evaluate("document.querySelector('[aria-label=\"选择 blocks\"]')")
    )
    for width, height in ((1440, 900), (390, 844)):
      self.call(
        "Emulation.setDeviceMetricsOverride",
        width=width,
        height=height,
        deviceScaleFactor=1,
        mobile=False,
      )
      wait_until(lambda width=width: self.evaluate("window.innerWidth") == width)
      self.assertFalse(
        self.evaluate("document.documentElement.scrollWidth > window.innerWidth")
      )
      self.evaluate(
        "document.querySelector('[aria-label=\"选择 search\"]')"
        ".scrollIntoView({block:'center'})"
      )
      data = self.call("Page.captureScreenshot", format="png")["data"]
      (self.artifacts / f"mcp-rediscovery-{width}.png").write_bytes(
        base64.b64decode(data)
      )
    self.evaluate("document.querySelector('[aria-label=\"选择 search\"]').click()")
    self.click("应用所选变更")
    wait_until(lambda: "所选工具已入库" in self.body())
    updated = self.client.get(base + f"/api/tools/{selected['id']}").json()["data"]
    self.assertEqual(updated["input_schema"], changed["inputSchema"])
    self.assertEqual(updated["name"], selected["name"])
    self.assertEqual(len(self.client.get(base + "/api/tools").json()["data"]), 2)
    wait_until(
      lambda: self.evaluate(
        "!document.querySelector('[aria-label=\"删除连接\"]').disabled"
      )
    )
    self.evaluate("document.querySelector('[aria-label=\"删除连接\"]').click()")
    wait_until(lambda: "删除 MCP 连接" in self.body())
    self.assertIn("2 个工具", self.body())
    self.assertIn("本地 blocks", self.body())
    self.assertEqual(len(self.client.get(base + "/api/tools").json()["data"]), 2)
    data = self.call("Page.captureScreenshot", format="png")["data"]
    (self.artifacts / "mcp-delete-impact-390.png").write_bytes(base64.b64decode(data))
    self.click("确认删除连接及工具")
    wait_until(lambda: "连接及所属工具已删除" in self.body())
    self.assertEqual(self.client.get(base + "/api/tools").json()["data"], [])
    self.assertEqual(self.client.get(base + "/api/mcp/connections").json()["data"], [])
    self.quit(host)
    self.assertEqual(host.wait(timeout=10), 0)

  def test_mcp_http_form_discover_and_execute(self):
    server = McpHttpServer()
    self.addCleanup(server.close)
    server.authorization = "Bearer native-test"
    host = self.launch()
    self.connect()
    base = self.state("ready")["base_url"]
    wait_until(lambda: "新建会话开始对话" in self.body())
    self.evaluate("document.querySelector('[aria-label=工具]').click()")
    wait_until(lambda: "工具库为空" in self.body())
    self.evaluate("document.querySelector('[aria-label=选择接入类型]').click()")
    self.click("接入 MCP 服务")
    wait_until(lambda: "暂无 MCP 连接" in self.body())
    self.evaluate("document.querySelector('[aria-label=\"接入 MCP 服务\"]').click()")
    self.evaluate(
      "document.querySelector('[aria-label=\"新建 Streamable HTTP 连接\"]').click()"
    )
    wait_until(
      lambda: self.evaluate("Boolean(document.getElementById('mcp-config_url'))")
    )
    self.assertFalse(
      self.evaluate("Boolean(document.getElementById('mcp-config_command'))")
    )
    self.fill("mcp-config_display_name", "远程 MCP 验收")
    self.fill("mcp-config_url", server.url + "/sse")
    self.replace(
      "mcp-config_headers", json.dumps({"Authorization": server.authorization})
    )
    self.click("保存连接")
    wait_until(lambda: "连接已保存" in self.body())
    wait_until(
      lambda: self.evaluate(
        "[...document.querySelectorAll('[aria-label=\"MCP 服务操作\"] button')]"
        ".some(button => button.textContent === '测试连接' && !button.disabled)"
      )
    )
    self.click("测试连接")
    wait_until(lambda: "连接测试成功" in self.body())
    self.click("发现工具")
    wait_until(lambda: "发现工具预览" in self.body())
    self.assertEqual(server.calls, 0)
    for width, height in ((1440, 900), (390, 844)):
      self.call(
        "Emulation.setDeviceMetricsOverride",
        width=width,
        height=height,
        deviceScaleFactor=1,
        mobile=False,
      )
      wait_until(lambda width=width: self.evaluate("window.innerWidth") == width)
      self.assertFalse(
        self.evaluate("document.documentElement.scrollWidth > window.innerWidth")
      )
      self.assertTrue(
        self.evaluate(
          "document.getElementById('mcp-config_headers')"
          ".getBoundingClientRect().width > 0"
        )
      )
      data = self.call("Page.captureScreenshot", format="png")["data"]
      (self.artifacts / f"mcp-http-{width}.png").write_bytes(base64.b64decode(data))
      self.evaluate(
        "document.getElementById('mcp-config_headers').scrollIntoView({block:'center'})"
      )
      self.assertTrue(
        self.evaluate(
          "(() => {const rect=document.getElementById('mcp-config_headers')"
          ".getBoundingClientRect();"
          "return rect.top >= 0 && rect.bottom <= innerHeight;})()"
        )
      )
      data = self.call("Page.captureScreenshot", format="png")["data"]
      (self.artifacts / f"mcp-http-headers-{width}.png").write_bytes(
        base64.b64decode(data)
      )
    self.call(
      "Emulation.setDeviceMetricsOverride",
      width=1440,
      height=900,
      deviceScaleFactor=1,
      mobile=False,
    )
    self.evaluate("document.querySelector('[aria-label=\"选择 search\"]').click()")
    self.click("导入所选工具")
    wait_until(lambda: "所选工具已入库" in self.body())
    self.evaluate("document.querySelector('[aria-label=\"打开工具 search\"]').click()")
    wait_until(
      lambda: self.evaluate("Boolean(document.getElementById('tool-input_query'))")
    )
    self.fill("tool-input_query", "native HTTP MCP")
    self.click("执行测试")
    wait_until(lambda: "测试成功" in self.body())
    self.assertIn('"query": "native HTTP MCP"', self.body())
    self.assertEqual(len(self.client.get(base + "/api/tools").json()["data"]), 1)
    self.assertEqual(server.sessions, set())
    self.quit(host)
    self.assertEqual(host.wait(timeout=10), 0)

  def test_python_source_preview_named_inputs_and_separate_debug_output(self):
    host = self.launch()
    self.connect()
    base = self.state("ready")["base_url"]
    wait_until(lambda: "新建会话开始对话" in self.body())
    self.evaluate("document.querySelector('[aria-label=工具]').click()")
    wait_until(lambda: "工具库为空" in self.body())
    self.evaluate("document.querySelector('[aria-label=选择接入类型]').click()")
    self.click("新建 Python 工具")
    wait_until(
      lambda: self.evaluate("Boolean(document.getElementById('tool-config_source'))")
    )
    self.fill("tool-config_display_name", "Python 订单计算")
    source = (
      "import sys\n\ndef main(quantity: int, price: float = 2.5):\n"
      "    print('native stdout')\n"
      "    print('native stderr', file=sys.stderr)\n"
      "    return {'total': quantity * price, 'ok': True}\n"
      + "# "
      + "long source line " * 50
      + "\n"
    )
    self.replace("tool-config_source", source)
    self.fill("tool-config_source", "# ")
    self.call("Input.imeSetComposition", text="中文", selectionStart=2, selectionEnd=2)
    self.call("Input.insertText", text="中文")
    self.press_key("Tab", "Tab", 9)
    last_line = "[...document.querySelectorAll('.cm-line')].at(-1).textContent"
    wait_until(lambda: self.evaluate(last_line) == "    # 中文")
    self.press_key("z", "KeyZ", 90, 2)
    wait_until(lambda: self.evaluate(last_line) == "# 中文")
    self.press_key("y", "KeyY", 89, 2)
    wait_until(lambda: self.evaluate(last_line) == "    # 中文")
    source += "    # 中文"
    self.press_key("Escape", "Escape", 27)
    self.press_key("Tab", "Tab", 9)
    self.assertNotEqual(
      self.evaluate("document.activeElement.id"), "tool-config_source"
    )
    wait_until(
      lambda: self.evaluate("Boolean(document.getElementById('tool-input_price'))")
    )
    self.assertEqual(
      self.evaluate("document.getElementById('tool-input_price').value"), ""
    )
    self.fill("tool-input_quantity", "4")
    self.click("执行测试")
    wait_until(lambda: "测试成功" in self.body())
    self.assertIn('"total": 10', self.body())
    self.assertIn("native stdout", self.body())
    self.assertIn("native stderr", self.body())
    self.assertIn("退出码：0", self.body())
    self.assertEqual(self.client.get(base + "/api/tools").json()["data"], [])
    self.click("保存工具")
    wait_until(lambda: "工具已保存" in self.body())
    saved = self.client.get(base + "/api/tools").json()["data"][0]
    self.assertEqual(saved["kind"], "python")
    self.assertNotIn("source", saved)
    detail = self.client.get(base + f"/api/tools/{saved['id']}").json()["data"]
    self.assertEqual(detail["source"], source)
    self.assertNotIn("未保存修改", self.body())
    self.assertTrue(self.evaluate("Boolean(document.querySelector('.cm-gutters'))"))
    self.assertTrue(
      self.evaluate("Boolean(document.querySelector('.cm-content span'))")
    )
    for width, height in ((1440, 900), (390, 844)):
      self.call(
        "Emulation.setDeviceMetricsOverride",
        width=width,
        height=height,
        deviceScaleFactor=1,
        mobile=False,
      )
      wait_until(lambda width=width: self.evaluate("window.innerWidth") == width)
      self.evaluate(
        "document.getElementById('tool-config_source').scrollIntoView({block:'center'})"
      )
      self.evaluate("document.querySelector('.cm-scroller').scrollLeft=0")
      self.assertTrue(
        self.evaluate(
          "document.querySelector('.cm-content').getBoundingClientRect().left >= "
          "document.querySelector('.cm-gutters').getBoundingClientRect().right"
        )
      )
      self.assertFalse(
        self.evaluate("document.documentElement.scrollWidth > window.innerWidth")
      )
      self.assertTrue(
        self.evaluate(
          "(() => {const scroller=document.querySelector('.cm-scroller');"
          "return scroller.scrollWidth > scroller.clientWidth;})()"
        )
      )
      data = self.call("Page.captureScreenshot", format="png")["data"]
      (self.artifacts / f"python-{width}.png").write_bytes(base64.b64decode(data))
      for area, selector in (
        ("preview", ".tool-python-preview"),
        ("result", "[aria-label='Python 调试输出']"),
      ):
        self.evaluate(
          f"document.querySelector({json.dumps(selector)}).scrollIntoView({{block:'center'}})"
        )
        self.assertFalse(
          self.evaluate("document.documentElement.scrollWidth > window.innerWidth")
        )
        data = self.call("Page.captureScreenshot", format="png")["data"]
        (self.artifacts / f"python-{area}-{width}.png").write_bytes(
          base64.b64decode(data)
        )
    self.call("Emulation.clearDeviceMetricsOverride")
    self.replace("tool-config_source", "def main(:")
    wait_until(lambda: "python_syntax" in self.body())
    self.assertTrue(
      self.evaluate("document.querySelector('button[form=tool-definition]').disabled")
    )
    self.assertEqual(
      self.evaluate("document.getElementById('tool-config_source').textContent"),
      "def main(:",
    )
    self.replace("tool-config_source", source)
    wait_until(
      lambda: (
        not self.evaluate(
          "document.querySelector('button[form=tool-definition]').disabled"
        )
      )
    )
    self.assertEqual(
      self.evaluate("document.getElementById('tool-input_quantity').value"), "4"
    )
    self.record(tool_id=saved["id"], source=saved["code_path"], pid=host.pid)

  def test_python_type_completion_schema_sync_and_retained_inputs(self):
    host = self.launch()
    self.connect()
    base = self.state("ready")["base_url"]
    wait_until(lambda: "新建会话开始对话" in self.body())
    self.evaluate("document.querySelector('[aria-label=工具]').click()")
    wait_until(lambda: "工具库为空" in self.body())
    self.evaluate("document.querySelector('[aria-label=选择接入类型]').click()")
    self.click("新建 Python 工具")
    wait_until(
      lambda: self.evaluate("Boolean(document.getElementById('tool-config_source'))")
    )
    self.fill("tool-config_display_name", "类型补齐与同步")
    source = (
      "def main(value, *, label: str | None = None): "
      "return {'value': value, 'label': label}\n"
    )
    self.replace("tool-config_source", source)
    save_disabled = "document.querySelector('button[form=tool-definition]').disabled"
    wait_until(lambda: "类型待补" in self.body())
    self.assertTrue(self.evaluate(save_disabled))
    self.click("确认源码变更")
    self.evaluate("""(() => {
      const select=document.querySelector('[aria-label="value 类型"]');
      select.value='integer'; select.dispatchEvent(new Event('change',{bubbles:true}));
    })()""")
    wait_until(lambda: not self.evaluate(save_disabled))
    self.assertTrue(
      self.evaluate("document.querySelector('[aria-label=\"label 类型\"]').disabled")
    )
    self.click("高级输入 JSON")
    schema = {
      "type": "object",
      "properties": {
        "value": {"type": "integer", "minimum": 2, "description": "至少两个"},
        "label": {"type": ["string", "null"]},
      },
      "required": ["value"],
      "additionalProperties": False,
    }
    self.replace("tool-config_input_schema", json.dumps(schema, ensure_ascii=False))
    self.replace("tool-input-json", '{"value": 3}')
    self.click("执行测试")
    wait_until(lambda: "测试成功" in self.body())
    self.assertIn('"value": 3', self.body())
    self.assertEqual(self.client.get(base + "/api/tools").json()["data"], [])
    self.replace(
      "tool-config_source", source.replace("return {", "# body changed\n    return {")
    )
    wait_until(lambda: not self.evaluate(save_disabled))
    self.assertEqual(
      self.evaluate(
        "JSON.parse(document.getElementById('tool-config_input_schema').value).properties.value.minimum"
      ),
      2,
    )
    self.click("保存工具")
    wait_until(lambda: "工具已保存" in self.body())
    saved = self.client.get(base + "/api/tools").json()["data"][0]
    self.assertEqual(saved["input_schema"], schema)
    for width, height in ((1440, 900), (390, 844)):
      self.call(
        "Emulation.setDeviceMetricsOverride",
        width=width,
        height=height,
        deviceScaleFactor=1,
        mobile=False,
      )
      self.evaluate(
        "document.querySelector('.tool-python-preview').scrollIntoView({block:'center'})"
      )
      self.assertFalse(
        self.evaluate("document.documentElement.scrollWidth > window.innerWidth")
      )
      data = self.call("Page.captureScreenshot", format="png")["data"]
      (self.artifacts / f"python-schema-{width}.png").write_bytes(
        base64.b64decode(data)
      )
    self.call("Emulation.clearDeviceMetricsOverride")
    self.replace("tool-config_source", source.replace("value,", "value: str,", 1))
    wait_until(lambda: "类型变化" in self.body())
    self.assertTrue(self.evaluate(save_disabled))
    self.click("确认源码变更")
    wait_until(lambda: not self.evaluate(save_disabled))
    self.assertEqual(
      self.evaluate("document.getElementById('tool-input-json').value"), '{"value": 3}'
    )
    self.assertIn("当前输入与结构不匹配", self.body())
    self.click("执行测试")
    wait_until(lambda: "input_validation" in self.body())
    current = self.client.get(base + f"/api/tools/{saved['id']}").json()["data"]
    self.assertEqual(current["input_schema"], schema)
    self.assertEqual(current["code_path"], saved["code_path"])
    self.record(tool_id=saved["id"], schema=schema, pid=host.pid)
    self.quit(host)
    self.assertEqual(host.wait(timeout=10), 0)

  def test_http_auth_password_reads_replaces_and_clears_direct_value(self):
    requests = []
    token = "ticket04-native-secret"
    replacement = "ticket04-native-replacement"

    class Handler(BaseHTTPRequestHandler):
      def do_GET(self):
        received = self.headers.get("Authorization")
        requests.append(received)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(
          json.dumps({"authenticated": bool(received), "count": 2}).encode()
        )

      def log_message(self, format, *args):
        pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    Thread(target=server.serve_forever, daemon=True).start()
    self.addCleanup(server.server_close)
    self.addCleanup(server.shutdown)
    host = self.launch()
    self.connect()
    base = self.state("ready")["base_url"]
    wait_until(lambda: "新建会话开始对话" in self.body())
    self.evaluate("document.querySelector('[aria-label=工具]').click()")
    wait_until(lambda: "工具库为空" in self.body())
    self.click("接入工具")
    wait_until(
      lambda: self.evaluate("Boolean(document.getElementById('tool-config_url'))")
    )
    self.fill("tool-config_display_name", "认证工具")
    self.fill("tool-config_url", f"http://127.0.0.1:{server.server_port}/")
    self.evaluate("""(() => {
      const field=document.getElementById('tool-config_auth-mode');
      field.value='bearer';
      field.dispatchEvent(new Event('change',{bubbles:true}));
    })()""")
    wait_until(
      lambda: self.evaluate("Boolean(document.querySelector('input[type=password]'))")
    )
    password_id = self.evaluate("document.querySelector('input[type=password]').id")
    self.fill(password_id, token)
    self.click("执行测试")
    wait_until(lambda: "测试成功" in self.body())
    self.assertEqual(requests, ["Bearer " + token])
    self.assertEqual(self.client.get(base + "/api/tools").json()["data"], [])
    self.click("保存工具")
    wait_until(lambda: len(self.client.get(base + "/api/tools").json()["data"]) == 1)
    tool = self.client.get(base + "/api/tools").json()["data"][0]
    tool_id = tool["id"]
    self.assertEqual(tool["auth"][0]["value"], token)
    self.assertNotIn("credential", tool["auth"][0])
    wait_until(lambda: "工具已保存" in self.body())
    self.assertEqual(
      self.evaluate("document.querySelector('input[type=password]').value"), token
    )
    self.assertNotIn("留空保留", self.body())
    for width, height in ((1440, 900), (390, 844)):
      self.call(
        "Emulation.setDeviceMetricsOverride",
        width=width,
        height=height,
        deviceScaleFactor=1,
        mobile=False,
      )
      wait_until(lambda width=width: self.evaluate("window.innerWidth") == width)
      self.evaluate(
        "document.querySelector('.tool-auth-editor').scrollIntoView({block:'center'})"
      )
      self.assertFalse(
        self.evaluate("document.documentElement.scrollWidth > window.innerWidth")
      )
      data = self.call("Page.captureScreenshot", format="png")["data"]
      (self.artifacts / f"auth-{width}.png").write_bytes(base64.b64decode(data))
    self.call("Emulation.clearDeviceMetricsOverride")
    self.replace("tool-config_display_name", "修改说明保留认证")
    self.click("保存工具")
    wait_until(
      lambda: (
        self.client.get(base + f"/api/tools/{tool_id}").json()["data"]["display_name"]
        == "修改说明保留认证"
      )
    )
    result = self.client.post(
      base + f"/api/tools/{tool_id}/execute", json={"inputs": {}}
    )
    self.assertEqual(result.json()["data"]["status"], "success")
    self.assertEqual(requests[-1], "Bearer " + token)
    wait_until(
      lambda: (
        not self.evaluate(
          "document.querySelector('button[form=tool-definition]').disabled"
        )
      )
    )
    self.replace(password_id, replacement)
    self.click("保存工具")
    wait_until(
      lambda: (
        self.client.get(base + f"/api/tools/{tool_id}").json()["data"]["auth"][0][
          "value"
        ]
        == replacement
      )
    )
    result = self.client.post(
      base + f"/api/tools/{tool_id}/execute", json={"inputs": {}}
    )
    self.assertEqual(requests[-1], "Bearer " + replacement)
    wait_until(
      lambda: (
        not self.evaluate(
          "document.querySelector('button[form=tool-definition]').disabled"
        )
      )
    )
    self.evaluate(
      f"document.getElementById({json.dumps(password_id)}).focus();document.getElementById({json.dumps(password_id)}).select()"
    )
    for event_type in ("keyDown", "keyUp"):
      self.call(
        "Input.dispatchKeyEvent",
        type=event_type,
        key="Backspace",
        code="Backspace",
        windowsVirtualKeyCode=8,
      )
    self.assertEqual(
      self.evaluate("document.querySelector('input[type=password]').value"), ""
    )
    self.click("保存工具")
    wait_until(
      lambda: (
        self.client.get(base + f"/api/tools/{tool_id}").json()["data"]["auth"][0][
          "value"
        ]
        == ""
      )
    )
    count = len(requests)
    result = self.client.post(
      base + f"/api/tools/{tool_id}/execute", json={"inputs": {}}
    ).json()["data"]
    self.assertEqual(result["error"]["code"], "authentication_missing")
    self.assertEqual(len(requests), count)
    storage = self.evaluate("JSON.stringify({...localStorage})")
    self.assertNotIn(token, storage)
    self.assertNotIn(replacement, storage)
    self.assertNotIn("auth_1", storage)
    self.record(
      tool_id=tool_id,
      requests_verified=True,
      auth_value_cleared=True,
      missing_result=result,
    )
    self.quit(host)
    self.assertEqual(host.wait(timeout=10), 0)

  def test_prototype_layout_type_tabs_and_hide_disabled(self):
    host = self.launch()
    self.connect()
    base = self.state("ready")["base_url"]
    definitions = [
      dict(
        kind="http",
        name="weather_query",
        display_name="天气查询",
        description="获取指定城市的天气信息",
        url="http://localhost/weather",
      ),
      dict(
        kind="http",
        name="inventory_query",
        display_name="库存查询",
        description="查询商品库存与可用数量",
        url="http://localhost/inventory",
      ),
      dict(
        kind="http",
        name="legacy_request",
        display_name="旧版接口",
        description="保留配置，暂停使用",
        url="http://localhost/legacy",
        enabled=False,
      ),
      dict(
        kind="python",
        name="calculate_total",
        display_name="金额计算",
        description="汇总项目金额",
        source="def main(quantity: int): return quantity * 2\n",
      ),
      dict(
        kind="mcp",
        name="repository_search",
        display_name="仓库搜索",
        description="检索代码仓库中的内容",
        connection_id="repository",
        remote_name="search",
      ),
      dict(
        kind="mcp",
        name="database_query",
        display_name="数据库查询",
        description="连接恢复后可重新启用",
        connection_id="database",
        remote_name="query",
        enabled=False,
      ),
    ]
    for definition in definitions:
      created = self.client.post(base + "/api/tools", json=definition)
      self.assertEqual(created.status_code, 201, created.text)
    wait_until(lambda: "新建会话开始对话" in self.body())
    self.evaluate("document.querySelector('[aria-label=工具]').click()")
    wait_until(
      lambda: (
        self.evaluate("document.querySelectorAll('.tool-library-list li').length") == 6
      )
    )
    self.assertIn("全部 (6)", self.body())
    self.assertIn("4 / 6 项已启用", self.body())
    self.evaluate("document.querySelector('.tool-library-list button').click()")
    wait_until(
      lambda: self.evaluate("Boolean(document.getElementById('tool-config_url'))")
    )
    self.assertEqual(
      self.evaluate(
        "document.querySelectorAll('.tool-primary-rail nav button').length"
      ),
      5,
    )
    for width, height in ((1440, 900), (1280, 800), (1024, 768), (390, 844)):
      self.call(
        "Emulation.setDeviceMetricsOverride",
        width=width,
        height=height,
        deviceScaleFactor=1,
        mobile=False,
      )
      wait_until(lambda width=width: self.evaluate("window.innerWidth") == width)
      self.assertFalse(
        self.evaluate("document.documentElement.scrollWidth > window.innerWidth")
      )
      layout = self.evaluate("""(() => {
        const rect=selector => document.querySelector(selector).getBoundingClientRect();
        const columns=document.querySelector('.tool-editor-layout').children;
        return {sidebar:rect('.tool-library-sidebar').width,
          toolbar:rect('.tool-detail-toolbar').height,
          left:columns[0].getBoundingClientRect().width,
          right:columns[1].getBoundingClientRect().width,
          toggleVisible:rect('.tool-disabled-filter').bottom
            <= rect('.tool-library-heading').bottom,
          toolbarRight:rect('.tool-toolbar-actions').right};
      })()""")
      self.assertTrue(layout["toggleVisible"])
      self.assertLessEqual(layout["toolbarRight"], width)
      if width >= 1280:
        self.assertAlmostEqual(layout["sidebar"], 256, delta=1)
        self.assertAlmostEqual(layout["toolbar"], 48, delta=1)
        self.assertAlmostEqual(layout["left"] / layout["right"], 7 / 5, delta=0.02)
      else:
        self.assertAlmostEqual(layout["left"], layout["right"], delta=1)
      screenshot = self.call("Page.captureScreenshot", format="png")["data"]
      (self.artifacts / f"prototype-{width}x{height}.png").write_bytes(
        base64.b64decode(screenshot)
      )
    self.call("Emulation.clearDeviceMetricsOverride")
    self.evaluate("document.querySelector('.tool-disabled-filter input').click()")
    wait_until(
      lambda: (
        self.evaluate("document.querySelectorAll('.tool-library-list li').length") == 4
      )
    )
    self.assertIn("全部 (4)", self.body())
    self.evaluate("document.querySelectorAll('.tool-library-tabs button')[3].click()")
    self.assertEqual(
      self.evaluate("document.querySelectorAll('.tool-library-list li').length"), 1
    )
    self.assertIn("repository / search", self.body())
    self.evaluate("document.querySelector('.tool-disabled-filter input').click()")
    self.assertEqual(
      self.evaluate("document.querySelectorAll('.tool-library-list li').length"), 2
    )
    self.assertEqual(
      self.evaluate("document.getElementById('tool-config_url').value"),
      "http://localhost/weather",
    )
    self.record(definitions=definitions, layout=layout)
    self.quit(host)
    self.assertEqual(host.wait(timeout=10), 0)

  def test_confirmed_create_with_lost_detail_response_retries_only_read(self):
    host = self.launch()
    self.connect()
    ready = self.state("ready")
    base = ready["base_url"]
    self.call("Page.enable")
    self.call(
      "Page.addScriptToEvaluateOnNewDocument",
      source=r"""(() => {
      const originalFetch=window.fetch;
      let detailResponseLost=false;
      window.toolCreateRequests=0;
      window.fetch=async (...args) => {
        const url=String(args[0]);
        const method=args[1]?.method ?? 'GET';
        if (method === 'POST' && url.endsWith('/api/tools')) {
          window.toolCreateRequests++;
        }
        const response=await originalFetch(...args);
        if (!detailResponseLost && method === 'GET'
          && /\/api\/tools\/[0-9a-f-]+$/.test(url)) {
          detailResponseLost=true;
          throw new TypeError('Injected loss of saved detail response');
        }
        return response;
      };
    })()""",
    )
    self.call("Page.reload")
    wait_until(
      lambda: (
        self.evaluate("window.toolCreateRequests === 0")
        and "新建会话开始对话" in self.body()
      )
    )
    self.evaluate("document.querySelector('[aria-label=工具]').click()")
    wait_until(lambda: "工具库为空" in self.body())
    self.click("接入工具")
    wait_until(
      lambda: self.evaluate("Boolean(document.getElementById('tool-config_url'))")
    )
    self.fill("tool-config_display_name", "已保存详情待重读")
    self.fill("tool-config_url", "http://localhost/example")
    self.click("保存工具")
    wait_until(lambda: "已保存，详情读取失败" in self.body())
    saved = self.client.get(base + "/api/tools").json()["data"]
    self.assertEqual(len(saved), 1)
    self.assertNotIn("保存结果不确定", self.body())
    self.assertTrue(
      self.evaluate("document.querySelector('button[form=tool-definition]').disabled")
    )
    self.assertEqual(self.evaluate("window.toolCreateRequests"), 1)
    self.screenshot()
    self.click("重新读取工具详情")
    wait_until(
      lambda: (
        not self.evaluate(
          "document.querySelector('button[form=tool-definition]').disabled"
        )
      )
    )
    self.assertIn(saved[0]["id"], self.body())
    self.assertNotIn("详情读取失败", self.body())
    self.assertEqual(self.evaluate("window.toolCreateRequests"), 1)
    self.assertEqual(len(self.client.get(base + "/api/tools").json()["data"]), 1)
    self.record(
      tool_id=saved[0]["id"], creates=self.evaluate("window.toolCreateRequests")
    )
    self.quit(host)
    self.assertEqual(host.wait(timeout=10), 0)

  def test_draft_navigation_disable_rename_and_delete(self):
    requests = []

    class Handler(BaseHTTPRequestHandler):
      def do_GET(self):
        requests.append(self.path)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"path": self.path}).encode())

      def log_message(self, format, *args):
        pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    Thread(target=server.serve_forever, daemon=True).start()
    self.addCleanup(server.server_close)
    self.addCleanup(server.shutdown)
    host = self.launch()
    self.connect()
    ready = self.state("ready")
    base = ready["base_url"]
    wait_until(lambda: "新建会话开始对话" in self.body())
    self.evaluate("document.querySelector('[aria-label=工具]').click()")
    wait_until(lambda: "工具库为空" in self.body())
    self.click("接入工具")
    wait_until(
      lambda: self.evaluate("Boolean(document.getElementById('tool-config_url'))")
    )
    self.fill("tool-config_display_name", "生命周期工具")
    self.fill("tool-config_url", f"http://127.0.0.1:{server.server_port}/draft")
    self.click("执行测试")
    wait_until(lambda: "测试成功" in self.body())
    self.assertEqual(self.client.get(base + "/api/tools").json()["data"], [])
    self.assertEqual(requests, ["/draft"])
    self.replace("tool-config_url", f"http://127.0.0.1:{server.server_port}/changed")
    wait_until(lambda: "修改前的测试结果" in self.body())
    self.evaluate("document.querySelector('[aria-label=\"会话与对话\"]').click()")
    wait_until(lambda: "未保存的工具修改" in self.body())
    self.click("继续编辑")
    self.assertEqual(self.client.get(base + "/api/tools").json()["data"], [])
    self.evaluate("document.querySelector('[aria-label=\"会话与对话\"]').click()")
    wait_until(lambda: "未保存的工具修改" in self.body())
    self.click("保存并离开")
    wait_until(
      lambda: "新建会话开始对话" in self.body() and "工具配置" not in self.body()
    )
    saved = self.client.get(base + "/api/tools").json()["data"][0]
    tool_id = saved["id"]
    self.assertTrue(saved["url"].endswith("/changed"))
    self.evaluate("document.querySelector('[aria-label=工具]').click()")
    wait_until(
      lambda: self.evaluate(
        "Boolean(document.querySelector('.tool-library-list button:not([disabled])'))"
      )
    )
    self.evaluate("document.querySelector('.tool-library-list button').click()")
    wait_until(
      lambda: self.evaluate("Boolean(document.getElementById('tool-config_enabled'))")
    )
    self.replace("tool-config_display_name", "改名后工具")
    self.replace("tool-config_name", "renamed_lifecycle")
    self.click("禁用此工具")
    self.assertEqual(
      self.evaluate("document.getElementById('tool-config_enabled').value"), "false"
    )
    self.click("保存工具")
    wait_until(lambda: "工具已保存" in self.body())
    saved = self.client.get(base + "/api/tools").json()["data"][0]
    self.assertEqual(saved["id"], tool_id)
    self.assertEqual(saved["name"], "renamed_lifecycle")
    self.assertFalse(saved["enabled"])
    rejected = self.client.post(
      base + f"/api/tools/{tool_id}/execute", json={"inputs": {}}
    ).json()["data"]
    self.assertEqual(rejected["error"]["code"], "disabled")
    self.click("执行测试")
    wait_until(lambda: "测试成功" in self.body())
    self.assertEqual(requests, ["/draft", "/changed"])
    for width, height in ((1440, 900), (390, 844)):
      self.call(
        "Emulation.setDeviceMetricsOverride",
        width=width,
        height=height,
        deviceScaleFactor=1,
        mobile=False,
      )
      wait_until(lambda width=width: self.evaluate("window.innerWidth") == width)
      self.assertFalse(
        self.evaluate("document.documentElement.scrollWidth > window.innerWidth")
      )
      screenshot = self.call("Page.captureScreenshot", format="png")["data"]
      (self.artifacts / f"draft-lifecycle-{width}.png").write_bytes(
        base64.b64decode(screenshot)
      )
    self.call("Emulation.clearDeviceMetricsOverride")
    self.evaluate("document.querySelector('[aria-label=\"删除工具\"]').click()")
    wait_until(lambda: "未来引用此 ID" in self.body())
    self.assertEqual(len(self.client.get(base + "/api/tools").json()["data"]), 1)
    self.click("确认删除")
    wait_until(lambda: "工具已删除" in self.body())
    self.assertEqual(self.client.get(base + "/api/tools").json()["data"], [])
    missing = self.client.post(
      base + f"/api/tools/{tool_id}/execute", json={"inputs": {}}
    ).json()["data"]
    self.assertEqual(missing["error"]["code"], "not_found")
    self.record(tool_id=tool_id, requests=requests)
    self.quit(host)
    self.assertEqual(host.wait(timeout=10), 0)

  def test_nested_parameters_modes_dialect_and_real_post(self):
    requests = []

    class Handler(BaseHTTPRequestHandler):
      def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        requests.append(
          {"path": self.path, "body": body, "headers": dict(self.headers)}
        )
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())

      def log_message(self, format, *args):
        pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    Thread(target=server.serve_forever, daemon=True).start()
    self.addCleanup(server.server_close)
    self.addCleanup(server.shutdown)
    host = self.launch()
    self.connect()
    ready = self.state("ready")
    wait_until(lambda: "新建会话开始对话" in self.body())
    self.evaluate("document.querySelector('[aria-label=工具]').click()")
    self.click("接入工具")
    wait_until(
      lambda: self.evaluate(
        "Boolean(document.getElementById('tool-config_display_name'))"
      )
    )
    self.fill("tool-config_display_name", "HTTP 嵌套参数验收")
    self.fill("tool-config_url", f"http://127.0.0.1:{server.server_port}/items/{{id}}")
    self.evaluate("""(() => {
      const field = document.getElementById('tool-config_method');
      field.value = [...field.options].find(o => o.text === 'POST').value;
      field.dispatchEvent(new Event('change', {bubbles:true}));
    })()""")
    schema = {
      "$schema": "https://json-schema.org/draft/2020-12/schema",
      "type": "object",
      "required": ["path"],
      "properties": {
        "path": {
          "type": "object",
          "required": ["id"],
          "properties": {"id": {"type": "string"}},
        },
        "query": {
          "type": "object",
          "properties": {"id": {"type": "integer", "minimum": 0}},
        },
        "body": {
          "type": "object",
          "required": ["nested"],
          "properties": {
            "nested": {
              "type": "object",
              "required": ["flag"],
              "properties": {
                "flag": {"type": "boolean"},
                "mail": {"type": "string", "format": "email"},
                "dateTime": {"type": "string", "format": "date-time"},
                "time": {"type": "string", "format": "time"},
              },
            }
          },
        },
      },
    }
    self.click("高级输入 JSON")
    self.replace("tool-config_input_schema", json.dumps(schema))
    self.replace("tool-config_headers", '{"X-Fixed":"native"}')
    self.replace("tool-config_output_schema", '{"type":"integer"}')
    self.click("保存工具")
    wait_until(lambda: "工具已保存" in self.body())
    saved = self.client.get(ready["base_url"] + "/api/tools").json()["data"][0]
    self.assertEqual(saved["method"], "POST")
    self.assertEqual(len(saved["parameters"]), 2)
    self.assertIn(
      "POST", self.evaluate("document.querySelector('.tool-summary-tags').innerText")
    )
    self.assertIn(
      "POST", self.evaluate("document.querySelector('.tool-type-tag').innerText")
    )
    self.click("JSON 参数")
    self.assertEqual(
      json.loads(self.evaluate("document.getElementById('tool-input-json').value")), {}
    )
    inputs = {
      "path": {"id": "a/b"},
      "query": {"id": 0},
      "body": {
        "nested": {
          "flag": False,
          "mail": "not-an-email",
          "dateTime": "not-a-date",
          "time": "not-a-time",
        },
        "extra": [None, False, 0, "", [], {}],
      },
    }
    self.replace("tool-input-json", json.dumps(inputs))
    self.click("参数表单")
    wait_until(
      lambda: self.evaluate(
        "Boolean(document.getElementById('tool-input_body_nested_mail'))"
      )
    )
    self.assertEqual(
      self.evaluate("document.getElementById('tool-input_body_nested_mail').type"),
      "text",
    )
    self.assertEqual(
      self.evaluate("document.getElementById('tool-input_body_nested_flag').value"),
      "false",
    )
    self.replace("tool-input_body_nested_dateTime", "not-a-date")
    self.replace("tool-input_body_nested_time", "not-a-time")
    self.click("JSON 参数")
    self.assertEqual(
      json.loads(self.evaluate("document.getElementById('tool-input-json').value")),
      inputs,
    )
    self.replace("tool-input-json", '{"body":')
    self.assertTrue(
      self.evaluate("document.querySelector('[aria-label=\"测试当前草稿\"]').disabled")
    )
    self.assertIn("JSON 无效", self.body())
    self.replace("tool-input-json", json.dumps(inputs))
    self.click("执行测试")
    wait_until(lambda: "测试成功" in self.body())
    self.assertEqual(requests[0]["path"], "/items/a%2Fb?id=0")
    self.assertEqual(requests[0]["body"], inputs["body"])
    self.assertEqual(requests[0]["headers"]["X-Fixed"], "native")
    self.assertEqual(
      json.loads(
        self.evaluate(
          "document.querySelector('[aria-label=\"工具返回 data\"]').textContent"
        )
      ),
      inputs["body"],
    )
    self.click("高级输入 JSON")
    self.replace(
      "tool-config_input_schema",
      json.dumps({**schema, "description": "schema changed"}),
    )
    self.click("保存工具")
    wait_until(lambda: "工具已保存" in self.body())
    wait_until(
      lambda: self.evaluate(
        "Boolean(document.querySelector('.tool-parameter-table-wrap'))"
      )
    )
    self.assertEqual(
      json.loads(self.evaluate("document.getElementById('tool-input-json').value")),
      inputs,
    )
    for width in (1440, 390):
      self.call(
        "Emulation.setDeviceMetricsOverride",
        width=width,
        height=900,
        deviceScaleFactor=1,
        mobile=False,
      )
      self.assertFalse(
        self.evaluate("document.documentElement.scrollWidth > window.innerWidth")
      )
      self.evaluate(
        "document.querySelector('.tool-parameter-table-wrap').scrollIntoView({block:'center'})"
      )
      self.assertLessEqual(
        self.evaluate(
          "document.querySelector('.tool-parameter-table-wrap').getBoundingClientRect().right"
        ),
        width,
      )
      screenshot = self.call("Page.captureScreenshot", format="png")["data"]
      (self.artifacts / f"parameters-{width}.png").write_bytes(
        base64.b64decode(screenshot)
      )
    self.record(schema=schema, inputs=inputs, requests=requests)
    self.quit(host)
    self.assertEqual(host.wait(timeout=10), 0)

  def test_create_reopen_test_theme_and_chat_navigation(self):
    payload = {"values": [None, False, 0, "", [], {}], "message": "真实响应"}

    class Handler(BaseHTTPRequestHandler):
      def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(payload, ensure_ascii=False).encode())

      def log_message(self, format, *args):
        pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    Thread(target=server.serve_forever, daemon=True).start()
    self.addCleanup(server.server_close)
    self.addCleanup(server.shutdown)
    host = self.launch()
    self.connect()
    ready = self.state("ready")
    wait_until(lambda: "新建会话开始对话" in self.body())
    navigation_preference = self.evaluate(
      "localStorage.getItem('shikigen.desktop-navigation-collapsed.v1')"
    )
    self.evaluate("document.querySelector('[aria-label=工具]').click()")
    wait_until(lambda: "工具库为空" in self.body())
    self.assertFalse(self.evaluate("Boolean(document.querySelector('.history'))"))
    self.assertFalse(
      self.evaluate(
        "Boolean(document.querySelector('.tool-primary-rail "
        '[aria-label="技能 · 暂未开放"]\'))'
      )
    )
    self.assertEqual(
      self.evaluate(
        "document.querySelectorAll('.tool-library-tabs [role=tab]').length"
      ),
      4,
    )
    self.click("接入工具")
    wait_until(
      lambda: self.evaluate(
        "Boolean(document.getElementById('tool-config_display_name'))"
      )
    )
    self.fill("tool-config_display_name", "桌面 HTTP 验收")
    self.fill("tool-config_url", f"http://127.0.0.1:{server.server_port}/")
    theme = self.evaluate("""(() => {
      const input = document.getElementById('tool-config_url');
      const button = document.querySelector('button[form=tool-definition]');
      const workspace = document.querySelector('.workspace');
      return {inputSlot:input.dataset.slot,
        inputHeight:input.getBoundingClientRect().height,
        background:getComputedStyle(button).backgroundColor,
        columns:getComputedStyle(workspace).gridTemplateColumns};
    })()""")
    self.assertEqual(theme["inputSlot"], "input")
    self.assertGreater(theme["inputHeight"], 30)
    self.assertEqual(theme["background"], "rgb(79, 70, 229)")
    self.click("保存工具")
    try:
      wait_until(lambda: "工具已保存" in self.body())
    except AssertionError:
      self.screenshot()
      self.record(body=self.body(), theme=theme)
      raise
    saved = self.client.get(ready["base_url"] + "/api/tools").json()["data"]
    self.assertEqual(len(saved), 1)
    tool_id = saved[0]["id"]
    self.assertEqual(saved[0]["display_name"], "桌面 HTTP 验收")
    self.evaluate("document.querySelector('[aria-label=\"返回工具列表\"]').click()")
    wait_until(
      lambda: self.evaluate(
        "Boolean(document.querySelector('.tool-library-list button:not([disabled])'))"
      )
    )
    self.evaluate("document.querySelector('.tool-library-list button').click()")
    wait_until(lambda: "执行测试" in self.body())
    self.assertIn(tool_id, self.body())
    self.click("执行测试")
    wait_until(lambda: "测试成功" in self.body())
    actual = self.evaluate(
      "document.querySelector('[aria-label=\"工具返回 data\"]').textContent"
    )
    self.assertEqual(json.loads(actual), payload)
    layout = self.evaluate("""(() => {
      const rect = selector => document.querySelector(selector).getBoundingClientRect();
      const columns = document.querySelector('.tool-editor-layout').children;
      const left = columns[0].getBoundingClientRect().width;
      const right = columns[1].getBoundingClientRect().width;
      return {rail:rect('.workspace > .navigation').width,
        sidebar:rect('.tool-library-sidebar').width,
        toolbar:rect('.tool-detail-toolbar').height,ratio:left / right};
    })()""")
    self.assertAlmostEqual(layout["rail"], 64, delta=1)
    self.assertAlmostEqual(layout["sidebar"], 256, delta=1)
    self.assertAlmostEqual(layout["toolbar"], 48, delta=1)
    self.assertAlmostEqual(layout["ratio"], 7 / 5, delta=0.02)
    self.screenshot()
    self.click("查看完整结果")
    wait_until(lambda: "完整工具结果" in self.body())
    self.assertIn('"duration_ms"', self.body())
    self.assertIn('"headers"', self.body())
    self.evaluate("document.querySelector('dialog[open] [aria-label=关闭]').click()")
    wait_until(
      lambda: not self.evaluate("Boolean(document.querySelector('dialog[open]'))")
    )
    for width, height in ((1440, 900), (1280, 800), (1024, 768), (390, 844)):
      self.call(
        "Emulation.setDeviceMetricsOverride",
        width=width,
        height=height,
        deviceScaleFactor=1,
        mobile=False,
      )
      wait_until(lambda width=width: self.evaluate("window.innerWidth") == width)
      overflow = self.evaluate(
        "document.documentElement.scrollWidth > window.innerWidth"
      )
      self.assertFalse(overflow, f"horizontal page overflow at {width}")
      screenshot = self.call("Page.captureScreenshot", format="png")["data"]
      (self.artifacts / f"tools-{width}x{height}.png").write_bytes(
        base64.b64decode(screenshot)
      )
    self.call("Emulation.clearDeviceMetricsOverride")
    wait_until(
      lambda: self.evaluate(
        "Boolean(document.querySelector('.workspace > .navigation'))"
      )
    )
    for event_type in ("keyDown", "keyUp"):
      self.call(
        "Input.dispatchKeyEvent",
        type=event_type,
        key="b",
        code="KeyB",
        windowsVirtualKeyCode=66,
        modifiers=2,
      )
    wait_until(
      lambda: self.evaluate(
        "Boolean(document.querySelector('dialog[open].sidebar-dialog'))"
      )
    )
    for event_type in ("keyDown", "keyUp"):
      self.call(
        "Input.dispatchKeyEvent",
        type=event_type,
        key="b",
        code="KeyB",
        windowsVirtualKeyCode=66,
        modifiers=2,
      )
    wait_until(
      lambda: not self.evaluate("Boolean(document.querySelector('dialog[open]'))")
    )
    self.evaluate("document.querySelector('[aria-label=\"会话与对话\"]').click()")
    wait_until(lambda: "新建会话开始对话" in self.body())
    self.assertTrue(self.evaluate("Boolean(document.querySelector('.history'))"))
    self.assertEqual(
      self.evaluate("localStorage.getItem('shikigen.desktop-navigation-collapsed.v1')"),
      navigation_preference,
    )
    self.record(ready=ready, tool_id=tool_id, theme=theme, layout=layout, data=payload)
    self.quit(host)
    self.assertEqual(host.wait(timeout=10), 0)


if __name__ == "__main__":
  result = unittest.TextTestRunner(verbosity=2).run(
    unittest.defaultTestLoader.loadTestsFromTestCase(ToolLibraryAcceptance)
  )
  sys.exit(0 if result.wasSuccessful() else 1)
