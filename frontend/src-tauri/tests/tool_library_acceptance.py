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
    self.assertTrue(
      self.evaluate(
        "document.querySelector('[aria-label=\"技能 · 暂未开放\"]').disabled"
      )
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
    self.evaluate(
      "document.querySelector('.workspace > .navigation "
      ".navigation-heading button').click()"
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
