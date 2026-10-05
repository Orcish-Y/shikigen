"""第 10 票：真实 Tauri 确认、取消保存、未知响应核实与重开。"""

import json
import unittest

import win32con
import win32gui
from desktop_cancel_fixtures import BODY
from message_drafts_acceptance import MessageDraftAcceptance
from window_acceptance import REPO, wait_until


class CancelPartialAcceptance(MessageDraftAcceptance):
  artifact_root = REPO / ".scratch/frontend-completion/ticket-10/native"

  def setUp(self):
    super().setUp()
    bootstrap = self.root / "app/desktop.py"
    bootstrap.write_text(
      bootstrap.read_text(encoding="utf-8").replace(
        "from runtime_fixtures import deterministic_agent",
        "from desktop_cancel_fixtures import cancel_agent as deterministic_agent",
      ),
      encoding="utf-8",
    )

  def instrument_sends(self):
    super().instrument_sends()
    self.call(
      "Page.addScriptToEvaluateOnNewDocument",
      source=r"""(() => {
      window.__cancelRequests=[];
      const original=window.fetch.bind(window);
      window.fetch=async (url,init)=> {
        const method=init?.method??'GET';
        if (String(url).includes('/api/')) window.__cancelRequests.push({
          url:String(url),method,at:performance.now()});
        if (window.__failCancelVerification && method==='GET'
          && /\/runs\/[^/]+$/.test(String(url))) {
          window.__failCancelVerification=false;
          return new Response('temporary GET failure',{
            status:503,headers:{'Retry-After':'1'}});
        }
        const response=await original(url,init);
        if (window.__loseCancelResponse && String(url).endsWith('/cancel')) {
          window.__loseCancelResponse=false;
          await response.text(); window.__failCancelVerification=true;
          return new Response('accepted response hidden',{status:500});
        }
        return response;
      };
    })()""",
    )
    self.call("Page.reload")
    wait_until(lambda: self.evaluate("Array.isArray(window.__cancelRequests)"))
    wait_until(lambda: "从一个想法开始" in self.body())

  def cancels(self):
    return self.evaluate(
      "window.__cancelRequests.filter(r=>r.method==='POST'"
      " && r.url.endsWith('/cancel'))"
    )

  def begin(self):
    host, ready, thread = self.start_empty()
    self.send("取消前已生成正文需要保存")
    wait_until(lambda: (self.root / "cancel-text-ready").exists())
    wait_until(lambda: "最后一段已接入正文" in self.body())
    return host, ready, thread

  def confirm(self):
    self.click("取消运行")
    wait_until(lambda: self.evaluate("Boolean(document.querySelector('dialog[open]'))"))
    self.assertEqual(self.evaluate("document.activeElement?.textContent"), "继续运行")
    self.assertEqual(
      self.evaluate("document.querySelector('.cancel-conversation')?.textContent"),
      "所属会话："
      + self.evaluate("document.querySelector('.chat-toolbar h1').textContent"),
    )
    self.assertIn("取消不会撤销已经发生的工具操作", self.body())
    self.click("确认取消")

  def saved(self, ready, thread):
    wait_until(
      lambda: (
        self.evaluate("document.querySelector('.toolbar-badge')?.textContent")
        == "已取消"
      )
    )
    wait_until(lambda: "因取消中止" in self.body())
    history = self.client.get(
      ready["base_url"] + f"/api/threads/{thread}/messages"
    ).json()["data"]
    ai = [m for m in history if m["content"]["type"] == "ai"]
    self.assertEqual(len(ai), 1)
    self.assertEqual(ai[0]["content"]["content"], BODY)
    self.assertEqual(ai[0]["content"]["generation_status"], "cancelled")
    self.assertEqual(ai[0]["content"]["tool_calls"], [])
    self.assertNotIn("生成中 · 尚未保存", self.body())
    return history

  def test_confirmation_dismissals_zero_post_then_cancel_and_restart_complete_body(
    self,
  ):
    host, ready, thread = self.begin()
    self.set_draft("取消时的下一条草稿")
    self.click("取消运行")
    wait_until(
      lambda: self.evaluate("document.activeElement?.textContent") == "继续运行"
    )
    self.screenshot()
    (self.artifacts / "window.png").rename(self.artifacts / "confirmation.png")
    self.call(
      "Input.dispatchKeyEvent",
      type="keyDown",
      key="Escape",
      code="Escape",
      windowsVirtualKeyCode=27,
    )
    self.call(
      "Input.dispatchKeyEvent",
      type="keyUp",
      key="Escape",
      code="Escape",
      windowsVirtualKeyCode=27,
    )
    wait_until(
      lambda: not self.evaluate("Boolean(document.querySelector('dialog[open]'))")
    )
    self.click("取消运行")
    self.evaluate(
      "document.querySelector('dialog[open] .overlay-heading button').click()"
    )
    wait_until(
      lambda: not self.evaluate("Boolean(document.querySelector('dialog[open]'))")
    )
    self.click("取消运行")
    self.evaluate(
      "document.querySelector('dialog[open]').dispatchEvent("
      "new MouseEvent('click',{bubbles:true,clientX:1,clientY:1}))"
    )
    wait_until(
      lambda: not self.evaluate("Boolean(document.querySelector('dialog[open]'))")
    )
    self.click("取消运行")
    self.click("继续运行")
    self.assertEqual(len(self.cancels()), 0)
    self.confirm()
    history = self.saved(ready, thread)
    self.assertEqual(len(self.cancels()), 1)
    self.assertEqual(self.draft(), "取消时的下一条草稿")
    self.screenshot()
    self.quit(host)
    self.assertEqual(host.wait(timeout=15), 0)
    assert self.ws is not None
    self.ws.close()
    self.ws = None
    second = self.launch()
    self.connect()
    reopened = self.state("ready")
    wait_until(lambda: "因取消中止" in self.body())
    current = self.client.get(
      reopened["base_url"] + f"/api/threads/{thread}/messages"
    ).json()["data"]
    self.assertEqual(current, history)
    self.assertEqual(self.draft(), "取消时的下一条草稿")
    self.record(
      history=history, ready=ready, reopened=reopened, thread=thread, draft=self.draft()
    )
    self.quit(second)
    self.assertEqual(second.wait(timeout=15), 0)

  def test_unknown_cancel_response_only_get_verifies_saved_terminal(self):
    host, ready, thread = self.begin()
    self.evaluate("window.__loseCancelResponse=true")
    self.confirm()
    wait_until(lambda: "取消结果待确认" in self.body())
    history = self.saved(ready, thread)
    wait_until(lambda: "取消结果待确认" not in self.body())
    self.assertEqual(len(self.cancels()), 1)
    requests = self.evaluate("window.__cancelRequests")
    self.assertEqual(sum(r["method"] == "POST" for r in requests), 2)
    self.assertTrue(
      any(
        r["method"] == "GET"
        and "/runs/" in r["url"]
        and not r["url"].endswith(("/stream", "/messages"))
        for r in requests
      )
    )
    self.screenshot()
    self.record(history=history, requests=requests, ready=ready, thread=thread)
    self.quit(host)
    self.assertEqual(host.wait(timeout=15), 0)

  def test_interrupted_cancel_invalidates_approval_without_tool_side_effect(self):
    self.fixture.env["DESKTOP_TEST_CANCEL_APPROVAL"] = "1"
    (self.root / "allow-cancel-model").touch()
    host, ready, thread = self.begin()
    wait_until(
      lambda: (
        self.evaluate("document.querySelector('.toolbar-badge')?.textContent")
        == "等待审批"
      )
    )
    before = self.client.get(
      ready["base_url"] + f"/api/threads/{thread}/messages"
    ).json()["data"][-1]
    content = before["content"]["content"]
    text = (
      content
      if isinstance(content, str)
      else "".join(
        block["text"]
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
      )
    )
    self.assertEqual(text, BODY)
    self.assertEqual(before["content"]["generation_status"], "complete")
    self.confirm()
    wait_until(
      lambda: (
        self.evaluate("document.querySelector('.toolbar-badge')?.textContent")
        == "已取消"
      )
    )
    history = self.client.get(
      ready["base_url"] + f"/api/threads/{thread}/messages"
    ).json()["data"]
    run = history[-1]["run_id"]
    replay = self.client.get(
      ready["base_url"] + f"/api/threads/{thread}/runs/{run}/stream"
    )
    replay.raise_for_status()
    events = [
      json.loads(line[6:])
      for line in replay.text.splitlines()
      if line.startswith("data: ")
    ]
    self.assertTrue(
      any(
        e.get("category") == "approval" and e.get("event_type") == "invalidated"
        for e in events
      )
    )
    self.assertEqual(history[-1]["content"]["generation_status"], "complete")
    self.assertEqual(history[-1], {**before, "run_status": "cancelled"})
    self.assertFalse((self.root / "cancel-side-effect").exists())
    self.assertEqual(len(self.cancels()), 1)
    self.assertNotIn("因取消中止", self.body())
    self.screenshot()
    self.record(
      history=history, events=events, requests=self.evaluate("window.__cancelRequests")
    )
    self.quit(host)
    self.assertEqual(host.wait(timeout=15), 0)

  def test_hidden_and_natural_terminal_close_confirmation_without_post(self):
    host, ready, thread = self.begin()
    self.click("取消运行")
    wait_until(lambda: self.evaluate("Boolean(document.querySelector('dialog[open]'))"))
    hwnd = self.window(host)
    win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
    wait_until(lambda: not win32gui.IsWindowVisible(hwnd))
    wait_until(
      lambda: not self.evaluate("Boolean(document.querySelector('dialog[open]'))")
    )
    self.tray_menu(host, "打开主窗口", native_command=True)
    wait_until(lambda: win32gui.IsWindowVisible(hwnd))
    wait_until(
      lambda: self.evaluate(
        "!document.querySelector('.composer .primary-button').disabled"
      )
    )
    self.click("取消运行")
    (self.root / "allow-cancel-model").touch()
    wait_until(
      lambda: (
        self.evaluate("document.querySelector('.toolbar-badge')?.textContent")
        == "已完成"
      )
    )
    wait_until(
      lambda: not self.evaluate("Boolean(document.querySelector('dialog[open]'))")
    )
    self.assertEqual(len(self.cancels()), 0)
    self.assertNotIn("因取消中止", self.body())
    self.screenshot()
    self.record(
      requests=self.evaluate("window.__cancelRequests"), ready=ready, thread=thread
    )
    self.quit(host)
    self.assertEqual(host.wait(timeout=15), 0)


if __name__ == "__main__":
  names = [
    name for name in CancelPartialAcceptance.__dict__ if name.startswith("test_")
  ]
  result = unittest.TextTestRunner(verbosity=2).run(
    unittest.TestSuite(CancelPartialAcceptance(name) for name in names)
  )
  raise SystemExit(0 if result.wasSuccessful() else 1)
