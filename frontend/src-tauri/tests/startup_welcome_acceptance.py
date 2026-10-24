"""新会话欢迎页：隔离桌面、真实 HTTP、持久草稿和托盘恢复。"""

import json
import socket
import unittest
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import win32con
import win32gui
from client_acceptance import ClientAcceptance
from window_acceptance import REPO, WINDOW, WindowAcceptance, wait_until


class StartupWelcomeAcceptance(WindowAcceptance):
  artifact_root = REPO / ".scratch/startup-new-conversation/native"
  body = ClientAcceptance.body
  click = ClientAcceptance.click
  set_draft = ClientAcceptance.set_draft
  select_thread = ClientAcceptance.select_thread

  @classmethod
  def setUpClass(cls):
    if (
      not WINDOW.is_file()
      or b"SHIKIGEN_ACCEPTANCE_DEV_ORIGIN" not in WINDOW.read_bytes()
    ):
      raise RuntimeError(
        "验收辅助程序缺失或过期；请在 frontend/src-tauri 执行 "
        "cargo build --locked --example backend_window"
      )
    with socket.socket() as probe:
      probe.bind(("127.0.0.1", 9238))
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
    if self.ws is not None and any(
      case is self
      for case, _ in self._outcome.result.failures + self._outcome.result.errors
    ):
      self.record(
        body=self.body(),
        page_url=self.evaluate("location.href"),
        viewport=self.evaluate("({width:innerWidth,height:innerHeight})"),
        requests=self.evaluate("window.__startupRequests ?? []"),
        page_errors=self.evaluate("window.__startupErrors ?? []"),
        backend=self.snapshot(),
      )
      self.screenshot()

  def active_thread(self):
    return self.evaluate(
      "document.querySelector('.session[aria-current=true]')?.dataset.conversationId"
    )

  def draft(self):
    return self.evaluate("document.getElementById('message-draft')?.value")

  def wait_for_send_ready(self):
    wait_until(
      lambda: self.evaluate(
        "[...document.querySelectorAll('button')]"
        ".some(button=>button.textContent.trim()==='发送'&&!button.disabled)"
      )
    )

  def instrument_requests(self, seed=None):
    script = """
      window.__startupRequests=[];
      window.__startupErrors=[];
      window.addEventListener('error',event=>window.__startupErrors.push(event.message));
      window.addEventListener('unhandledrejection',event=>window.__startupErrors.push(String(event.reason)));
      const fetchFromBackend=window.fetch.bind(window);
      window.fetch=async(input,init)=>{
        const url=new URL(typeof input==='string'?input:input.url,location.href);
        const request={path:url.pathname,method:init?.method??'GET',
          body:init?.body?JSON.parse(init.body):null};
        if(url.pathname.startsWith('/api/'))window.__startupRequests.push(request);
        try {
          const response=await fetchFromBackend(input,init);
          request.status=response.status;
          return response;
        } catch(error) {request.error=String(error);throw error;}
      };
    """
    if seed is not None:
      script += (
        "localStorage.setItem('shikigen.message-drafts.v1',"
        + json.dumps(json.dumps(seed, ensure_ascii=False))
        + ");"
      )
    self.call("Page.enable")
    self.call("Page.addScriptToEvaluateOnNewDocument", source=script)
    self.call("Page.reload")
    wait_until(lambda: self.evaluate("Array.isArray(window.__startupRequests)"))
    wait_until(lambda: "从一个想法开始" in self.body())

  def assert_welcome(self):
    wait_until(lambda: "从一个想法开始" in self.body())
    self.assertIsNone(self.active_thread())
    self.assertTrue(self.evaluate("!document.getElementById('message-draft').disabled"))
    self.assertNotIn("Thread not found", self.body())
    self.assertNotIn("会话历史读取失败", self.body())
    self.assertNotIn("自动恢复已停止", self.body())

  def test_stale_selection_and_full_restart_keep_welcome_and_both_drafts(self):
    host = self.launch()
    self.connect()
    ready = self.state("ready")
    thread_id = self.client.post(ready["base_url"] + "/api/threads").json()["thread_id"]
    self.instrument_requests(
      {
        "schema": 1,
        "selected": "deleted-thread",
        "drafts": [[thread_id, {"text": "历史会话草稿", "version": 1}]],
        "submissions": [],
        "newConversationDraft": {"text": "欢迎页草稿", "version": 2},
      }
    )
    wait_until(
      lambda: self.evaluate("document.querySelectorAll('.session').length") == 1
    )
    self.assert_welcome()
    self.assertEqual(self.draft(), "欢迎页草稿")
    requests = self.evaluate("window.__startupRequests")
    self.assertTrue(requests)
    self.assertTrue(all(request["path"] == "/api/threads" for request in requests))
    self.assertTrue(all(request["method"] == "GET" for request in requests))
    self.screenshot()
    (self.artifacts / "startup.png").write_bytes(
      (self.artifacts / "window.png").read_bytes()
    )
    self.select_thread(thread_id)
    wait_until(lambda: self.draft() == "历史会话草稿")
    self.wait_for_send_ready()
    self.click("新建")
    self.assert_welcome()
    self.assertEqual(self.draft(), "欢迎页草稿")
    self.select_thread(thread_id)
    self.set_draft("重启后仍保留的历史草稿")
    self.quit(host)
    self.assertEqual(host.wait(timeout=15), 0)
    self.ws.close()
    host = self.launch()
    self.connect()
    self.state("ready")
    self.assert_welcome()
    self.assertEqual(self.draft(), "欢迎页草稿")
    self.select_thread(thread_id)
    wait_until(lambda: self.draft() == "重启后仍保留的历史草稿")
    self.wait_for_send_ready()
    self.record(requests=requests, thread_id=thread_id, body=self.body())
    self.screenshot()
    self.quit(host)
    self.assertEqual(host.wait(timeout=15), 0)

  def test_first_send_once_and_tray_reopen_preserves_current_conversation(self):
    host = self.launch()
    self.connect()
    ready = self.state("ready")
    self.instrument_requests()
    self.assert_welcome()
    original = "  欢迎页首次发送\n    保留中文缩进  "
    self.set_draft(original)
    self.click("发送")
    self.evaluate(
      "[...document.querySelectorAll('button')]"
      ".find(button=>button.textContent.trim()==='确认发送中…')?.click()"
    )
    thread_id = wait_until(self.active_thread)
    wait_until(
      lambda: (
        self.evaluate("document.querySelector('.toolbar-badge')?.textContent.trim()")
        == "已完成"
      )
    )
    wait_until(lambda: self.draft() == "")
    messages = self.client.get(
      ready["base_url"] + f"/api/threads/{thread_id}/messages"
    ).json()["data"]
    users = [message for message in messages if message["content"]["type"] == "human"]
    self.assertEqual(len(users), 1)
    self.assertEqual(users[0]["content"]["content"], original)
    requests = self.evaluate("window.__startupRequests")
    posts = [request for request in requests if request["method"] == "POST"]
    self.assertEqual(
      [request["path"] for request in posts],
      ["/api/threads", f"/api/threads/{thread_id}/stream"],
    )
    self.set_draft("托盘恢复保留的下一条")
    window = self.window(host)
    win32gui.PostMessage(window, win32con.WM_CLOSE, 0, 0)
    wait_until(lambda: not win32gui.IsWindowVisible(window))
    self.tray_menu(host, "打开主窗口", native_command=True)
    wait_until(lambda: win32gui.IsWindowVisible(window))
    wait_until(lambda: self.active_thread() == thread_id)
    self.assertEqual(self.draft(), "托盘恢复保留的下一条")
    self.wait_for_send_ready()
    self.record(
      requests=requests, thread_id=thread_id, messages=messages, body=self.body()
    )
    self.screenshot()
    self.quit(host)
    self.assertEqual(host.wait(timeout=15), 0)


if __name__ == "__main__":
  unittest.main()
