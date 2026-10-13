"""组件接入 04：真实 Tauri 推理事实、正文流、焦点、阅读与会话隔离。"""

import json
import unittest

from chat_reading_acceptance import ChatReadingAcceptance
from desktop_reasoning_fixtures import (
  ANSWER_START,
  REASONING_TEXT,
  SAVED_ANSWER_CONTENT,
  SAVED_CONTENT,
)
from window_acceptance import REPO, wait_until


class ReasoningAcceptance(ChatReadingAcceptance):
  artifact_root = REPO / ".scratch/frontend-component-libraries/verification/native"

  def setUp(self):
    super().setUp()
    bootstrap = self.root / "app/desktop.py"
    script = bootstrap.read_text(encoding="utf-8")
    original = (
      "from desktop_reading_fixtures import reading_agent as deterministic_agent"
    )
    self.assertIn(original, script)
    bootstrap.write_text(
      script.replace(
        original,
        "from desktop_reasoning_fixtures import "
        "create_reasoning_agent as deterministic_agent",
      ),
      encoding="utf-8",
    )

  def dispatch_key(self, key, code, key_code):
    for event_type in ("keyDown", "keyUp"):
      key_event_parameters = {
        "type": event_type,
        "key": key,
        "code": code,
        "windowsVirtualKeyCode": key_code,
      }
      # Native Enter activation needs its character/keypress, not only keydown.
      if event_type == "keyDown" and key == "Enter":
        key_event_parameters.update(text="\r", unmodifiedText="\r")
      self.call("Input.dispatchKeyEvent", **key_event_parameters)

  def capture_clipboard(self, *, should_fail_clipboard_write=False):
    # Clipboard is the external boundary. The native DOM handler still supplies
    # its real text; a controlled failure also checks user-visible feedback.
    self.evaluate(
      "Object.defineProperty(navigator, 'clipboard', {configurable:true,value:{"
      "writeText:async text=>{window.__copiedText=text;"
      + ("throw new Error('clipboard denied');" if should_fail_clipboard_write else "")
      + "}}})"
    )

  def read_history(self, backend_snapshot, thread):
    return self.client.get(
      backend_snapshot["base_url"] + f"/api/threads/{thread}/messages"
    ).json()["data"]

  def start_reasoning(self):
    host, backend_snapshot, thread = self.start_empty()
    self.send("真实推理呈现验收")
    wait_until(lambda: (self.root / "reasoning-answer-started").exists())
    wait_until(
      lambda: "正文流开始" in self.body() and "模型提供的推理原文" in self.body()
    )
    self.assertTrue(self.evaluate("Boolean(window.__TAURI_INTERNALS__)"))
    self.evaluate("""(() => {
      const panel = document.querySelector('section[aria-label="思考链路"]');
      window.__reasoningPanel = panel;
      window.__reasoningToggle = panel.querySelector('button[aria-expanded]');
      window.__reasoningBody = document.getElementById(
        window.__reasoningToggle.getAttribute('aria-controls'));
      window.__reasoningRawToggle = [...panel.querySelectorAll('summary')]
        .find(e => e.textContent === '查看原始思考块');
    })()""")
    history = self.read_history(backend_snapshot, thread)
    reasoning = next(
      message for message in history if message["content"]["type"] == "ai"
    )
    self.assertEqual(reasoning["content"]["content"], SAVED_CONTENT)
    self.assertEqual(reasoning["content"]["generation_status"], "complete")
    self.assertEqual(
      self.evaluate("window.__reasoningToggle.getAttribute('aria-expanded')"),
      "true",
    )
    self.assertIn("生成中 · 尚未保存", self.body())
    return host, backend_snapshot, thread, reasoning

  def show_full_reasoning(self):
    self.evaluate("""(() => {
      const trigger = [...window.__reasoningPanel.querySelectorAll('button')]
        .find(e => e.textContent === '查看完整思考');
      window.__reasoningViewTrigger = trigger;
      trigger.focus({preventScroll:true}); trigger.click();
    })()""")
    wait_until(lambda: self.evaluate("Boolean(document.querySelector('dialog[open]'))"))
    self.assertEqual(
      self.evaluate("document.querySelector('dialog[open] h2').textContent"),
      "完整思考内容",
    )
    self.assertEqual(
      self.evaluate("document.querySelector('dialog[open] pre').textContent"),
      REASONING_TEXT,
    )

  def close_full_reasoning(self):
    self.dispatch_key("Escape", "Escape", 27)
    wait_until(
      lambda: self.evaluate("document.querySelectorAll('dialog[open]').length") == 0
    )
    self.assertTrue(
      self.evaluate("document.activeElement === window.__reasoningViewTrigger")
    )

  def test_saved_reasoning_copy_full_view_fold_and_body_stream_preserve_reading(self):
    host, backend_snapshot, thread, reasoning = self.start_reasoning()
    self.assertIn("未提供思考文本。", self.body())
    self.assertIn("网页图片未自动加载", self.body())
    self.assertFalse(self.evaluate("Boolean(window.__reasoningInjected)"))
    self.assertEqual(
      self.evaluate(
        "document.querySelectorAll('section[aria-label=\"思考链路\"]').length"
      ),
      2,
    )
    self.assertEqual(
      self.evaluate(
        "document.querySelectorAll('.message-content script,.message-content img')"
        ".length"
      ),
      0,
    )
    unknown_blocks = self.evaluate(
      "[...document.querySelectorAll('pre[aria-label=\"内容块 JSON\"]')]"
      ".map(e=>e.textContent)"
    )
    self.assertEqual([json.loads(text) for text in unknown_blocks], SAVED_CONTENT[3:])
    self.evaluate("window.__reasoningRawToggle.click()")
    raw_text = self.evaluate(
      "window.__reasoningPanel.querySelector('pre[aria-label=\"原始思考块 JSON\"]')"
      ".textContent"
    )
    self.assertEqual(json.loads(raw_text), SAVED_CONTENT[1])
    self.assertTrue(self.evaluate("window.__reasoningRawToggle.parentElement.open"))
    self.capture_clipboard()
    self.evaluate(
      "window.__reasoningPanel.querySelector('[aria-label=\"复制思考内容\"]').click()"
    )
    wait_until(lambda: self.evaluate("window.__copiedText") == REASONING_TEXT)
    self.set_draft("查看推理仍保留这份草稿")
    self.show_full_reasoning()
    self.screenshot()
    (self.artifacts / "reasoning-full-view.png").write_bytes(
      (self.artifacts / "window.png").read_bytes()
    )
    self.close_full_reasoning()
    self.assertEqual(self.draft(), "查看推理仍保留这份草稿")
    self.capture_clipboard(should_fail_clipboard_write=True)
    self.evaluate(
      "window.__reasoningPanel.querySelector('[aria-label=\"复制思考内容\"]').click()"
    )
    wait_until(lambda: "复制失败，可手动选择" in self.body())
    self.assertEqual(self.evaluate("window.__copiedText"), REASONING_TEXT)
    reading = self.pause_at(".assistant p[data-reading-anchor]:nth-of-type(4)")
    self.evaluate(
      "window.__reasoningToggle.focus({preventScroll:true});"
      "window.__reasoningToggle.click()"
    )
    self.assert_anchor(reading)
    self.assertTrue(self.evaluate("window.__reasoningBody.hidden"))
    (self.root / "allow-reasoning-update").touch()
    wait_until(lambda: (self.root / "reasoning-answer-updated").exists())
    wait_until(lambda: "正文增量 7" in self.body())
    self.assert_anchor(reading)
    self.assertTrue(self.geometry()["newContent"])
    self.assertEqual(
      self.evaluate("window.__reasoningToggle.getAttribute('aria-expanded')"),
      "false",
    )
    self.assertTrue(self.evaluate("window.__reasoningBody.hidden"))
    self.assertTrue(
      self.evaluate(
        "window.__reasoningRawToggle.isConnected"
        " && window.__reasoningRawToggle.parentElement.open"
      )
    )
    self.assertTrue(
      self.evaluate("document.activeElement === window.__reasoningToggle")
    )
    self.screenshot()
    (self.artifacts / "folded-body-stream.png").write_bytes(
      (self.artifacts / "window.png").read_bytes()
    )
    self.dispatch_key("Enter", "Enter", 13)
    wait_until(lambda: not self.evaluate("window.__reasoningBody.hidden"))
    self.assert_anchor(reading)
    (self.root / "allow-reasoning-completion").touch()
    wait_until(
      lambda: (
        self.evaluate("document.querySelector('.toolbar-badge').textContent")
        == "已完成"
      )
    )
    self.assert_anchor(reading)
    self.assertTrue(
      self.evaluate("document.activeElement === window.__reasoningToggle")
    )
    self.assertEqual(
      self.evaluate("window.__reasoningToggle.getAttribute('aria-expanded')"), "true"
    )
    self.assertNotIn("生成中 · 尚未保存", self.body())
    history = self.read_history(backend_snapshot, thread)
    self.assertEqual(history[-1]["content"]["content"], SAVED_ANSWER_CONTENT)
    self.assertEqual(history[1]["content"]["content"], SAVED_CONTENT)
    self.assertEqual(self.evaluate("window.__sends.length"), 1)
    self.record(
      backend_snapshot=backend_snapshot,
      thread=thread,
      reasoning=reasoning,
      history=history,
      reading=reading,
      final_reading=self.geometry(),
      raw_text=raw_text,
      unknown_blocks=unknown_blocks,
      copied_text=self.evaluate("window.__copiedText"),
      requests=self.evaluate("window.__sends"),
      body=self.body(),
    )
    self.screenshot()
    self.quit(host)
    self.assertEqual(host.wait(timeout=15), 0)

  def test_narrow_keyboard_session_switch_and_cancel_keep_real_reasoning(self):
    host, backend_snapshot, thread, reasoning = self.start_reasoning()
    reading = self.pause_at(".assistant p[data-reading-anchor]:nth-of-type(4)")
    self.call(
      "Emulation.setDeviceMetricsOverride",
      width=390,
      height=780,
      deviceScaleFactor=1,
      mobile=False,
    )
    self.assert_anchor(reading)
    self.evaluate("window.__reasoningToggle.focus({preventScroll:true})")
    self.dispatch_key(" ", "Space", 32)
    wait_until(lambda: self.evaluate("window.__reasoningBody.hidden"))
    self.assert_anchor(reading)
    self.dispatch_key("Enter", "Enter", 13)
    wait_until(lambda: not self.evaluate("window.__reasoningBody.hidden"))
    # Reading moves to the action the user is about to open. Closing the drawer
    # must retain this position, rather than an off-screen synthetic click.
    reading = self.pause_at('section[aria-label="思考链路"] .reasoning-actions')
    self.show_full_reasoning()
    self.assertEqual(
      self.evaluate(
        "Math.round(document.querySelector('dialog[open]').getBoundingClientRect()"
        ".width)"
      ),
      390,
    )
    for _ in range(5):
      self.dispatch_key("Tab", "Tab", 9)
      self.assertTrue(
        self.evaluate("Boolean(document.activeElement.closest('dialog[open]'))")
      )
    self.screenshot()
    (self.artifacts / "narrow-reasoning.png").write_bytes(
      (self.artifacts / "window.png").read_bytes()
    )
    self.close_full_reasoning()
    self.assert_anchor(reading)
    self.call("Emulation.clearDeviceMetricsOverride")
    self.assert_anchor(reading)
    self.set_draft("推理会话自己的草稿")
    self.click("新建")
    wait_until(lambda: "从一个想法开始" in self.body())
    other = self.evaluate(
      "document.querySelector('.session[aria-current=true]').dataset.conversationId"
    )
    self.assertNotEqual(other, thread)
    self.assertNotIn("模型提供的推理原文", self.body())
    self.assertEqual(self.draft(), "")
    self.select_thread(thread)
    wait_until(lambda: "模型提供的推理原文" in self.body())
    self.assertEqual(self.draft(), "推理会话自己的草稿")
    self.assert_anchor(reading)
    self.assertIn("生成中 · 尚未保存", self.body())
    self.assertEqual(self.evaluate("window.__sends.length"), 1)
    self.click("取消运行")
    wait_until(lambda: "取消本次运行？" in self.body())
    self.click("确认取消")
    wait_until(
      lambda: (
        self.evaluate("document.querySelector('.toolbar-badge').textContent")
        == "已取消"
      )
    )
    wait_until(lambda: "因取消中止" in self.body())
    history = self.read_history(backend_snapshot, thread)
    self.assertEqual(history[1]["content"]["content"], SAVED_CONTENT)
    self.assertEqual(history[1]["content"]["generation_status"], "complete")
    self.assertEqual(history[-1]["content"]["content"], ANSWER_START)
    self.assertEqual(history[-1]["content"]["generation_status"], "cancelled")
    self.assertIn("模型提供的推理原文", self.body())
    self.assertNotIn("生成中 · 尚未保存", self.body())
    self.assertEqual(self.draft(), "推理会话自己的草稿")
    self.assert_anchor(reading)
    self.record(
      backend_snapshot=backend_snapshot,
      thread=thread,
      other=other,
      reasoning=reasoning,
      history=history,
      reading=reading,
      final_reading=self.geometry(),
      requests=self.evaluate("window.__sends"),
      body=self.body(),
    )
    self.screenshot()
    self.quit(host)
    self.assertEqual(host.wait(timeout=15), 0)


if __name__ == "__main__":
  names = [
    "test_saved_reasoning_copy_full_view_fold_and_body_stream_preserve_reading",
    "test_narrow_keyboard_session_switch_and_cancel_keep_real_reasoning",
  ]
  result = unittest.TextTestRunner(verbosity=2).run(
    unittest.TestSuite(ReasoningAcceptance(name) for name in names)
  )
  raise SystemExit(0 if result.wasSuccessful() else 1)
