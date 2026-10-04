"""票据 04：真实 Tauri 页面、公开 HTTP 与隔离持久数据库。"""

import time
import unittest

from run_reconstruction_acceptance import ReconstructionAcceptance
from window_acceptance import REPO, wait_until


class MessageDraftAcceptance(ReconstructionAcceptance):
  artifact_root = REPO / ".scratch/frontend-completion/ticket-04/native"

  def draft(self):
    return self.evaluate("document.getElementById('message-draft')?.value")

  def instrument_sends(self):
    # BackendClient 在启动时绑定 fetch；必须在下次页面脚本执行前安装包装。
    self.call("Page.enable")
    self.call(
      "Page.addScriptToEvaluateOnNewDocument",
      source="""
      window.__sends = [];
      const original = window.fetch.bind(window);
      window.fetch = async (url, init) => {
        if (init?.method !== 'POST' || !String(url).endsWith('/stream'))
          return original(url, init);
        window.__sends.push({url:String(url), body:JSON.parse(init.body)});
        const response = await original(url, init);
        if (window.__delayAcceptance) {
          window.__delayAcceptance = false;
          await new Promise(resolve => window.__releaseAcceptance = resolve);
        }
        if (window.__hideAcceptance) {
          window.__hideAcceptance = false;
          await response.text();
          const error = JSON.stringify({detail:'测试传输层隐藏已接受响应'});
          return new Response(error, {status:500});
        }
        return response;
      };
    """,
    )
    self.call("Page.reload")
    wait_until(lambda: self.evaluate("Array.isArray(window.__sends)"))
    wait_until(lambda: "从一个想法开始" in self.body())

  def start_empty(self):
    host = self.launch()
    self.connect()
    ready = self.state("ready")
    wait_until(lambda: "新建会话开始对话" in self.body())
    self.click("新建")
    wait_until(
      lambda: self.evaluate(
        "Boolean(document.getElementById('message-draft')"
        " && !document.getElementById('message-draft').disabled)"
      )
    )
    wait_until(lambda: "从一个想法开始" in self.body())
    self.instrument_sends()
    thread = self.evaluate(
      "document.querySelector('.session[aria-current=true]').title"
    ).split("会话 ID：")[-1]
    return host, ready, thread

  def users(self, ready, thread):
    history = self.client.get(
      ready["base_url"] + f"/api/threads/{thread}/messages"
    ).json()["data"]
    return [message for message in history if message["content"]["type"] == "human"]

  def test_original_enter_composition_and_draft_survive_native_restart(self):
    host, ready, thread = self.start_empty()
    self.evaluate("document.getElementById('message-draft').focus()")
    # WebView 的真实合成输入入口；系统 IME 候选面板/物理键盘留在票据 23。
    self.call(
      "Input.imeSetComposition", text="中文候选", selectionStart=4, selectionEnd=4
    )
    self.assertTrue(
      self.evaluate(
        "document.getElementById('message-draft').dispatchEvent("
        "new KeyboardEvent('keydown', {key:'Enter', keyCode:229,"
        "isComposing:true, bubbles:true, cancelable:true}))"
      )
    )
    self.assertEqual(self.evaluate("window.__sends.length"), 0)
    self.call("Input.insertText", text="中文候选")
    time.sleep(0.08)
    original = "  中文原文\n    缩进  \n"
    self.set_draft(original)
    self.call(
      "Input.dispatchKeyEvent",
      type="keyDown",
      key="Enter",
      code="Enter",
      windowsVirtualKeyCode=13,
    )
    self.call(
      "Input.dispatchKeyEvent",
      type="keyUp",
      key="Enter",
      code="Enter",
      windowsVirtualKeyCode=13,
    )
    wait_until(lambda: len(self.users(ready, thread)) == 1)
    wait_until(lambda: "已完成" in self.body())
    self.assertEqual(self.users(ready, thread)[0]["content"]["content"], original)
    self.assertEqual(self.evaluate("window.__sends[0].body.message"), original)
    next_draft = "下一条草稿\n  重启保留"
    self.set_draft(next_draft)
    self.screenshot()
    self.quit(host)
    self.assertEqual(host.wait(timeout=15), 0)
    self.ws.close()
    self.ws = None
    second = self.launch()
    self.connect()
    reopened = self.state("ready")
    wait_until(lambda: self.draft() == next_draft)
    self.assertEqual(len(self.users(reopened, thread)), 1)
    self.record(
      original=original,
      draft=self.draft(),
      users=self.users(reopened, thread),
      ready=ready,
      reopened=reopened,
      composition="CDP WebView 合成输入；未覆盖系统候选面板和物理键盘",
    )
    self.quit(second)
    self.assertEqual(second.wait(timeout=15), 0)

  def test_late_acceptance_and_unknown_send_manual_confirmation(
    self,
  ):
    host, ready, thread = self.start_empty()
    self.evaluate("window.__delayAcceptance = true")
    self.send("第一次原文")
    wait_until(lambda: self.evaluate("Boolean(window.__releaseAcceptance)"))
    self.set_draft("请求期间新编辑的文字")
    self.evaluate("window.__releaseAcceptance()")
    wait_until(lambda: "已完成" in self.body())
    self.assertEqual(self.draft(), "请求期间新编辑的文字")
    self.evaluate("window.__hideAcceptance = true")
    self.send("第二次待核对原文")
    wait_until(lambda: "发送结果待确认" in self.body())
    wait_until(
      lambda: self.evaluate(
        "document.querySelector('[aria-label=\"发送结果核对\"] select')"
        "?.options.length === 3"
      )
    )
    self.assertEqual(len(self.users(ready, thread)), 2)
    self.screenshot()
    (self.artifacts / "unknown-send.png").write_bytes(
      (self.artifacts / "window.png").read_bytes()
    )
    self.click("查询状态")
    wait_until(
      lambda: "发送结果待确认" in self.body() and "正在核实" not in self.body()
    )
    self.assertEqual(self.evaluate("window.__sends.length"), 2)
    self.evaluate(
      "(() => { const select = document.querySelector("
      "'[aria-label=\"发送结果核对\"] select');"
      "const value = select.options[1].value;"
      "Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,'value')"
      ".set.call(select,value);"
      "select.dispatchEvent(new Event('change',{bubbles:true})); })()"
    )
    self.click("确认此消息对应本次发送")
    wait_until(lambda: "发送结果待确认" not in self.body())
    self.assertEqual(self.draft(), "")
    self.assertEqual(self.evaluate("window.__sends.length"), 2)
    self.record(
      ready=ready,
      users=self.users(ready, thread),
      requests=self.evaluate("window.__sends"),
      draft=self.draft(),
    )
    self.screenshot()
    self.quit(host)
    self.assertEqual(host.wait(timeout=15), 0)

  def test_explicit_new_task_is_a_new_post_and_preserves_newer_draft(self):
    host, ready, thread = self.start_empty()
    self.evaluate("window.__hideAcceptance = true")
    self.send("可能已经执行的原文")
    wait_until(lambda: "发送结果待确认" in self.body())
    wait_until(lambda: "已完成" in self.body())
    self.set_draft("另写的新草稿")
    self.click("作为新任务发送")
    self.assertIn("可能造成重复执行", self.body())
    self.screenshot()
    (self.artifacts / "confirm-new-task.png").write_bytes(
      (self.artifacts / "window.png").read_bytes()
    )
    self.click("确认发起新任务")
    wait_until(lambda: len(self.users(ready, thread)) == 2)
    wait_until(lambda: "已完成" in self.body())
    self.assertEqual(self.draft(), "另写的新草稿")
    self.assertEqual(self.evaluate("window.__sends.length"), 2)
    self.assertTrue(
      all(
        message["content"]["content"] == "可能已经执行的原文"
        for message in self.users(ready, thread)
      )
    )
    self.record(
      ready=ready,
      users=self.users(ready, thread),
      requests=self.evaluate("window.__sends"),
      draft=self.draft(),
    )
    self.screenshot()
    self.quit(host)
    self.assertEqual(host.wait(timeout=15), 0)

  def test_running_draft_stays_editable_and_enter_cannot_invoke_run_action(self):
    self.fixture.env["DESKTOP_TEST_RESIDENT_TASK"] = "1"
    host, ready, thread = self.start_empty()
    self.send("运行期草稿验收")
    wait_until(lambda: (self.root / "executing").exists())
    self.set_draft("运行中可以编辑")
    self.evaluate("document.getElementById('message-draft').focus()")
    self.call(
      "Input.dispatchKeyEvent",
      type="keyDown",
      key="Enter",
      code="Enter",
      windowsVirtualKeyCode=13,
    )
    self.call(
      "Input.dispatchKeyEvent",
      type="keyUp",
      key="Enter",
      code="Enter",
      windowsVirtualKeyCode=13,
    )
    self.assertEqual(self.draft(), "运行中可以编辑")
    self.assertEqual(self.evaluate("window.__sends.length"), 1)
    self.assertIn("运行结束后手动发送", self.body())
    self.call("Page.reload")
    wait_until(lambda: self.draft() == "运行中可以编辑")
    self.assertEqual(len(self.users(ready, thread)), 1)
    self.record(
      ready=ready, users=self.users(ready, thread), draft=self.draft(), body=self.body()
    )
    self.screenshot()
    self.quit(host)
    self.assertEqual(host.wait(timeout=15), 0)


if __name__ == "__main__":
  names = [name for name in MessageDraftAcceptance.__dict__ if name.startswith("test_")]
  suite = unittest.TestSuite(MessageDraftAcceptance(name) for name in names)
  result = unittest.TextTestRunner(verbosity=2).run(suite)
  raise SystemExit(0 if result.wasSuccessful() else 1)
