"""第 08 票真实 Tauri：公开 HTTP 记录、工具卡片与完整查看／复制。"""

import json
import unittest

from desktop_tool_records_fixtures import CASES, LONG_RESULT
from markdown_content_acceptance import MarkdownAcceptance
from message_drafts_acceptance import MessageDraftAcceptance
from window_acceptance import REPO, wait_until


class ToolRecordsAcceptance(MessageDraftAcceptance):
  artifact_root = REPO / ".scratch/frontend-completion/ticket-08/native"

  def setUp(self):
    super().setUp()
    if (
      self._testMethodName
      != "test_failure_arrival_respects_manual_collapse_of_waiting_card"
    ):
      (self.root / "allow-tool-results").touch()
    bootstrap = self.root / "app/desktop.py"
    bootstrap.write_text(
      bootstrap.read_text(encoding="utf-8").replace(
        "from runtime_fixtures import deterministic_agent",
        "from desktop_tool_records_fixtures import "
        "tool_records_agent as deterministic_agent",
      ),
      encoding="utf-8",
    )

  def card(self, identity):
    return f"document.querySelector('[data-tool-id={json.dumps(identity)}]')"

  def expanded(self, identity, section="card"):
    selector = (
      ".tool-summary" if section == "card" else f"[aria-controls$='-{section}']"
    )
    return self.evaluate(
      f"{self.card(identity)}.querySelector({json.dumps(selector)})"
      ".getAttribute('aria-expanded') === 'true'"
    )

  def toggle(self, identity, section="card"):
    selector = (
      ".tool-summary" if section == "card" else f"[aria-controls$='-{section}']"
    )
    self.evaluate(
      f"{self.card(identity)}.querySelector({json.dumps(selector)}).click()"
    )

  def history(self, ready, thread):
    response = self.client.get(ready["base_url"] + f"/api/threads/{thread}/messages")
    response.raise_for_status()
    return response.json()["data"]

  def start_records(self):
    host, ready, thread = self.start_empty()
    self.send("验证完整工具记录")
    wait_until(lambda: "工具记录已产生" in self.body())
    wait_until(
      lambda: (
        self.evaluate("document.querySelector('.toolbar-badge').textContent")
        == "已完成"
      )
    )
    wait_until(
      lambda: self.evaluate("document.querySelectorAll('.tool-block').length") == 9
    )
    return host, ready, thread

  def test_true_status_pairing_full_records_empty_values_and_complete_copy(self):
    host, ready, thread = self.start_records()
    history = self.history(ready, thread)
    agent = next(
      item
      for item in history
      if item["content"]["type"] == "ai" and item["content"]["tool_calls"]
    )
    tools = [item for item in history if item["content"]["type"] == "tool"]
    self.assertEqual(len(tools), 8)
    self.assertEqual(
      self.evaluate(
        "[...document.querySelectorAll('.assistant .tool-block')]"
        ".map(e=>e.dataset.toolId)"
      ),
      [f"fixture-{case}" for case in CASES],
    )
    self.assertEqual(
      self.evaluate("document.querySelectorAll('article.message.tool').length"), 1
    )
    self.assertEqual(
      self.evaluate(
        f"{self.card('fixture-second')}.querySelector('.tool-status').textContent"
      ),
      "已返回",
    )
    self.assertEqual(
      self.evaluate(
        f"{self.card('fixture-failed')}.querySelector('.tool-status').textContent"
      ),
      "工具失败",
    )
    self.assertEqual(
      self.evaluate(
        f"{self.card('fixture-waiting')}.querySelector('.tool-status').textContent"
      ),
      "等待结果",
    )
    self.assertIn(
      "所属运行已结束", self.evaluate(f"{self.card('fixture-waiting')}.textContent")
    )
    self.assertIn(
      "未找到对应调用", self.evaluate(f"{self.card('fixture-orphan')}.textContent")
    )
    for case in CASES:
      self.assertEqual(self.expanded(f"fixture-{case}"), case == "failed")
    self.assertTrue(self.expanded("fixture-failed", "result"))
    self.assertFalse(self.expanded("fixture-failed", "parameters"))
    self.assertFalse(self.expanded("fixture-failed", "artifact"))
    for result in tools:
      identity = result["content"]["tool_call_id"]
      card = self.card(identity)
      if not self.expanded(identity):
        self.toggle(identity)
      self.toggle(identity, "raw")
      raw = self.evaluate(
        f"{card}.querySelector('pre[aria-label=\"结果记录 JSON\"]').textContent"
      )
      public_record = json.loads(raw)
      # The UI may have SSE fields until terminal GET completes; wait for the
      # full history record before comparing every outer field.
      wait_until(
        lambda card=card, result=result: (
          json.loads(
            self.evaluate(
              f"{card}.querySelector('pre[aria-label=\"结果记录 JSON\"]').textContent"
            )
          )
          == result
        )
      )
      self.assertEqual(public_record["seq"], result["seq"])
      artifact = result["content"].get("artifact")
      has_section = self.evaluate(
        f"Boolean({card}.querySelector('[aria-controls$=\"-artifact\"]'))"
      )
      self.assertEqual(has_section, artifact is not None)
      if has_section:
        self.toggle(identity, "artifact")
        text = (
          artifact
          if isinstance(artifact, str)
          else json.dumps(artifact, ensure_ascii=False, indent=2)
        )
        self.assertEqual(
          self.evaluate(f"{card}.querySelector('[id$=\"-artifact\"] pre').textContent"),
          text,
        )
      self.assertIn(f"结果 seq：{result['seq']}", self.evaluate(f"{card}.textContent"))
    self.toggle("fixture-first", "parameters")
    self.assertEqual(
      json.loads(
        self.evaluate(
          f"{self.card('fixture-first')}"
          ".querySelector('pre[aria-label=\"工具参数 JSON\"]').textContent"
        )
      ),
      {"case": "first"},
    )
    self.assertIn(
      f"调用 seq：{agent['seq']}",
      self.evaluate(f"{self.card('fixture-first')}.textContent"),
    )
    self.assertIn(
      "different_result_name",
      self.evaluate(f"{self.card('fixture-first')}.textContent"),
    )
    self.assertIn(
      "已返回，正文为空", self.evaluate(f"{self.card('fixture-first')}.textContent")
    )
    self.assertEqual(
      self.evaluate(
        f"{self.card('fixture-failed')}.querySelector('.plain-content').textContent"
      ),
      LONG_RESULT,
    )
    self.assertEqual(
      self.evaluate(
        f"{self.card('fixture-failed')}"
        ".querySelectorAll('.message-text strong, .message-text img, "
        ".message-text a').length"
      ),
      0,
    )
    MarkdownAcceptance.capture_clipboard(self)
    self.evaluate(
      f"{self.card('fixture-failed')}.querySelector('[aria-label=\"复制完整内容\"]').click()"
    )
    wait_until(lambda: self.evaluate("window.__copied") == LONG_RESULT)
    self.set_draft("查看工具内容仍保留草稿")
    self.evaluate(
      f"(() => {{const b={self.card('fixture-failed')}"
      ".querySelector('.message-content-actions button'); "
      "window.__trigger=b; b.focus(); b.click();})()"
    )
    wait_until(lambda: self.evaluate("Boolean(document.querySelector('dialog[open]'))"))
    self.assertEqual(
      self.evaluate("document.querySelector('dialog[open] pre').textContent"),
      LONG_RESULT,
    )
    self.screenshot()
    (self.artifacts / "desktop-tool-content.png").write_bytes(
      (self.artifacts / "window.png").read_bytes()
    )
    self.evaluate("document.querySelector('dialog[open] [aria-label=关闭]').click()")
    wait_until(lambda: self.evaluate("document.activeElement === window.__trigger"))
    self.assertEqual(self.draft(), "查看工具内容仍保留草稿")
    self.assertEqual(self.evaluate("window.__sends.length"), 1)
    self.call(
      "Emulation.setDeviceMetricsOverride",
      width=390,
      height=780,
      deviceScaleFactor=1,
      mobile=False,
    )
    self.evaluate(f"{self.card('fixture-failed')}.scrollIntoView({{block:'start'}})")
    self.assertLessEqual(
      self.evaluate("document.querySelector('.chat-workspace').scrollWidth"), 390
    )
    self.assertLessEqual(
      self.evaluate(
        f"{self.card('fixture-failed')}.querySelector('.message-text').clientHeight"
      ),
      320,
    )
    self.assertGreater(
      self.evaluate(
        f"{self.card('fixture-failed')}.querySelector('.message-text').scrollHeight"
      ),
      320,
    )
    self.screenshot()
    (self.artifacts / "narrow-tool-records.png").write_bytes(
      (self.artifacts / "window.png").read_bytes()
    )
    self.record(
      ready=ready,
      thread=thread,
      history=history,
      copied=self.evaluate("window.__copied"),
      narrow="真实 WebView 390×780 设备视口模拟；物理窗口联合验收留在第 23 票",
    )
    self.quit(host)
    self.assertEqual(host.wait(timeout=15), 0)

  def test_manual_collapse_survives_replay_selection_and_native_restart_resets(self):
    host, ready, thread = self.start_records()
    self.toggle("fixture-failed", "result")
    self.toggle("fixture-failed")
    self.assertFalse(self.expanded("fixture-failed"))
    self.click("刷新数据")
    wait_until(
      lambda: "已完成" in self.body() and "正在读取会话历史" not in self.body()
    )
    self.assertFalse(self.expanded("fixture-failed"))
    self.click("新建")
    wait_until(lambda: "从一个想法开始" in self.body())
    self.select_thread(thread)
    wait_until(
      lambda: self.evaluate(
        "Boolean(document.querySelector('[data-tool-id=fixture-failed]'))"
      )
    )
    self.assertFalse(self.expanded("fixture-failed"))
    self.toggle("fixture-failed")
    self.assertFalse(self.expanded("fixture-failed", "result"))
    self.toggle("fixture-failed")
    self.screenshot()
    self.quit(host)
    self.assertEqual(host.wait(timeout=15), 0)
    self.ws.close()
    self.ws = None
    reopened = self.launch()
    self.connect()
    second = self.state("ready")
    wait_until(
      lambda: self.evaluate(
        "Boolean(document.querySelector('[data-tool-id=fixture-failed]'))"
      )
    )
    self.assertTrue(self.expanded("fixture-failed"))
    self.assertTrue(self.expanded("fixture-failed", "result"))
    self.assertFalse(self.expanded("fixture-failed", "parameters"))
    self.assertFalse(self.expanded("fixture-failed", "artifact"))
    self.assertEqual(
      len([r for r in self.history(second, thread) if r["content"]["type"] == "human"]),
      1,
    )
    self.record(
      ready=ready,
      reopened=second,
      thread=thread,
      manual_collapse=True,
      restart_defaults=True,
    )
    self.quit(reopened)
    self.assertEqual(reopened.wait(timeout=15), 0)

  def test_parameters_artifacts_and_independent_result_full_view_and_copy(self):
    host, ready, thread = self.start_records()
    history = self.history(ready, thread)
    agent = next(
      item
      for item in history
      if item["content"]["type"] == "ai" and item["content"]["tool_calls"]
    )
    MarkdownAcceptance.capture_clipboard(self)

    def verify_actions(selector, text):
      self.evaluate("window.__copied = null")
      self.evaluate(f'{selector}.querySelector("[aria-label=复制]").click()')
      wait_until(lambda: self.evaluate("window.__copied") == text)
      self.evaluate(
        f'(() => {{const b={selector}.querySelector(".content-actions > button");'
        "window.__recordTrigger=b; b.focus(); b.click();})()"
      )
      wait_until(
        lambda: self.evaluate('Boolean(document.querySelector("dialog[open]"))')
      )
      self.assertEqual(
        self.evaluate('document.querySelectorAll("dialog[open]").length'), 1
      )
      self.assertEqual(
        self.evaluate('document.querySelector("dialog[open] pre").textContent'), text
      )
      self.evaluate('document.querySelector("dialog[open] [aria-label=关闭]").click()')
      wait_until(
        lambda: self.evaluate("document.activeElement === window.__recordTrigger")
      )

    self.toggle("fixture-first")
    self.toggle("fixture-first", "parameters")
    verify_actions(
      self.card("fixture-first") + ".querySelector('[id$=-parameters] .content-block')",
      json.dumps(
        agent["content"]["tool_calls"][0]["args"], ensure_ascii=False, indent=2
      ),
    )
    artifacts = []
    for record in history:
      if (
        record["content"]["type"] != "tool" or record["content"].get("artifact") is None
      ):
        continue
      identity = record["content"]["tool_call_id"]
      if not self.expanded(identity):
        self.toggle(identity)
      self.toggle(identity, "artifact")
      artifact = record["content"]["artifact"]
      text = (
        artifact
        if isinstance(artifact, str)
        else json.dumps(artifact, ensure_ascii=False, indent=2)
      )
      verify_actions(
        self.card(identity) + ".querySelector('[id$=-artifact] .content-block')",
        text,
      )
      artifacts.append({"id": identity, "text": text})
    orphan = next(
      r for r in history if r["content"].get("tool_call_id") == "fixture-orphan"
    )
    self.toggle("fixture-orphan")
    self.toggle("fixture-orphan", "result")
    body = orphan["content"]["content"]
    text = (
      body if isinstance(body, str) else json.dumps(body, ensure_ascii=False, indent=2)
    )
    self.evaluate("window.__copied = null")
    self.evaluate(
      self.card("fixture-orphan")
      + ".querySelector('[aria-label=复制完整内容]').click()"
    )
    try:
      wait_until(lambda: self.evaluate("window.__copied") == text)
    except AssertionError:
      self.record(
        ready=ready,
        thread=thread,
        expected=text,
        copied=self.evaluate("window.__copied"),
        current_history=self.history(ready, thread),
        original_result=self.evaluate(
          self.card("fixture-orphan")
          + ".querySelector('pre[aria-label=\"结果记录 JSON\"]').textContent"
        ),
      )
      self.screenshot()
      raise
    self.evaluate(
      self.card("fixture-orphan")
      + '.querySelector(".message-content-actions > button").click()'
    )
    wait_until(lambda: self.evaluate('Boolean(document.querySelector("dialog[open]"))'))
    self.assertEqual(
      self.evaluate('document.querySelector("dialog[open] pre").textContent'), text
    )
    self.screenshot()
    self.evaluate('document.querySelector("dialog[open] [aria-label=关闭]").click()')
    self.assertEqual(self.evaluate("window.__sends.length"), 1)
    self.assertEqual(self.history(ready, thread), history)
    self.record(
      ready=ready,
      thread=thread,
      history=history,
      parameters=agent["content"]["tool_calls"][0]["args"],
      artifacts_copied=artifacts,
      independent_result_copied=text,
    )
    self.quit(host)
    self.assertEqual(host.wait(timeout=15), 0)

  def test_failure_arrival_respects_manual_collapse_of_waiting_card(self):
    host, ready, thread = self.start_empty()
    self.send("等待时手动收起")
    wait_until(
      lambda: self.evaluate(
        "Boolean(document.querySelector('[data-tool-id=fixture-failed]'))"
      )
    )
    self.assertFalse(self.expanded("fixture-failed"))
    self.toggle("fixture-failed")
    self.toggle("fixture-failed")
    (self.root / "allow-tool-results").touch()
    wait_until(
      lambda: (
        self.evaluate(
          f"{self.card('fixture-failed')}.querySelector('.tool-status').textContent"
        )
        == "工具失败"
      )
    )
    wait_until(
      lambda: (
        self.evaluate("document.querySelector('.toolbar-badge').textContent")
        == "已完成"
      )
    )
    self.assertFalse(self.expanded("fixture-failed"))
    self.click("刷新数据")
    wait_until(lambda: "正在读取会话历史" not in self.body())
    self.assertFalse(self.expanded("fixture-failed"))
    self.record(
      ready=ready,
      thread=thread,
      after_failure="用户手动收起，失败到达后保持折叠",
      history=self.history(ready, thread),
    )
    self.screenshot()
    self.quit(host)
    self.assertEqual(host.wait(timeout=15), 0)


if __name__ == "__main__":
  unittest.main()
