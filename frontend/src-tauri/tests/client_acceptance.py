"""Desktop business reads, sends and recovery against actual isolated Python."""

import json
import socket
import unittest
from concurrent.futures import ThreadPoolExecutor

import win32api
import win32con
import win32event
from window_acceptance import REPO, WindowAcceptance, wait_until


class ClientAcceptance(WindowAcceptance):
  artifact_root = REPO / ".scratch/frontend-completion/ticket-01-native"

  def body(self):
    return self.evaluate("document.body.innerText")

  def click(self, label):
    self.assertTrue(
      self.evaluate(
        "(() => { const button = [...document.querySelectorAll('button')]"
        f".find(b => b.textContent.trim() === {json.dumps(label)});"
        "if (!button || button.disabled) return false;"
        "button.click(); return true; })()"
      )
    )

  def test_page_reads_persisted_messages_and_run_then_sends_only_on_click(self):
    host = self.launch()
    self.connect()
    ready = self.state("ready")
    url = ready["base_url"]
    for origin in ("http://127.0.0.1:5173", "http://tauri.localhost"):
      preflight = self.client.options(
        url + "/api/threads",
        headers={
          "Origin": origin,
          "Access-Control-Request-Method": "POST",
          "Access-Control-Request-Headers": "content-type",
        },
      )
      self.assertEqual(preflight.status_code, 200)
      self.assertEqual(preflight.headers["access-control-allow-origin"], origin)
    denied = self.client.options(
      url + "/api/threads",
      headers={
        "Origin": "https://unrelated.example",
        "Access-Control-Request-Method": "POST",
      },
    )
    self.assertEqual(denied.status_code, 400)
    thread = self.client.post(url + "/api/threads").json()["thread_id"]
    response = self.client.post(
      url + f"/api/threads/{thread}/stream",
      json={"message": "验收已保存的会话"},
      timeout=20,
    )
    self.assertEqual(response.status_code, 200)
    self.call("Page.reload")
    try:
      wait_until(lambda: "验收已保存的会话" in self.body(), timeout=10)
    except AssertionError:
      self.record(body=self.body(), url=self.evaluate("location.href"), ready=ready)
      self.screenshot()
      raise
    self.click("运行详情")
    wait_until(lambda: "已完成" in self.body())
    self.assertIn("Run ID", self.body())
    self.evaluate("document.querySelector('[aria-label=关闭]').click()")
    self.send("由页面显式发送")
    wait_until(lambda: "由页面显式发送" in self.body())
    messages = wait_until(
      lambda: self.client.get(url + f"/api/threads/{thread}/messages").json()["data"]
    )
    self.assertEqual(
      sum(m["content"].get("content") == "由页面显式发送" for m in messages), 1
    )
    self.assertEqual(self.counts(), (1, 1))
    self.record(ready=ready, thread=thread, messages=messages)
    self.screenshot()
    self.quit(host)
    self.assertEqual(host.wait(timeout=10), 0)

  def send(self, message):
    wait_until(
      lambda: self.evaluate(
        "Boolean(document.querySelector('.session[aria-current=true]'))"
      )
    )
    self.set_draft(message)
    wait_until(
      lambda: self.evaluate(
        "[...document.querySelectorAll('button')]"
        ".some(b => b.textContent.trim() === '发送' && !b.disabled)"
      )
    )
    self.click("发送")

  def set_draft(self, message):
    self.evaluate(
      "(() => { const input = document.getElementById('message-draft');"
      "Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set"
      f".call(input, {json.dumps(message)});"
      "input.dispatchEvent(new Event('input', {bubbles:true})); })()"
    )

  def select_thread(self, thread_id):
    wait_until(
      lambda: self.evaluate(
        "(() => { const button = [...document.querySelectorAll('.session')]"
        f".find(b => b.title.includes({json.dumps(thread_id)}));"
        "if (!button) return false; button.click(); return true; })()"
      )
    )

  def instrument_fetch(self, hold_messages=False):
    # Transport boundary only: actual server responses still supply every fact.
    # Optionally delay delivery of one parsed JSON response across host retry.
    self.call("Page.enable")
    self.call(
      "Page.addScriptToEvaluateOnNewDocument",
      source="""
      window.__requests = [];
      const original = window.fetch.bind(window);
      window.fetch = async (input, init) => {
        if (!String(input).includes('/api/')) return original(input, init);
        const item = {url:String(input), method:init?.method ?? 'GET', aborted:false};
        window.__requests.push(item);
        init?.signal?.addEventListener('abort', () => item.aborted = true);
        const response = await original(input, init);
        if (HOLD_MESSAGES && !window.__held && item.url.endsWith('/messages')) {
          window.__held = true;
          const read = response.json.bind(response);
          response.json = async () => {
            const data = await read();
            window.__lateReady = true;
            await new Promise(resolve => window.__releaseLate = resolve);
            return data;
          };
        }
        return response;
      };
    """.replace("HOLD_MESSAGES", "true" if hold_messages else "false"),
    )
    self.call("Page.reload")
    wait_until(lambda: self.evaluate("Array.isArray(window.__requests)"), timeout=5)

  def kill_and_retry_on_next_port(self, ready):
    handles = self.fixture.process_handles()
    win32api.TerminateProcess(handles[0], 73)
    wait_until(lambda: self.snapshot().get("can_retry"))
    for handle in handles:
      self.assertEqual(
        win32event.WaitForSingleObject(handle, 5000), win32con.WAIT_OBJECT_0
      )
    occupied = socket.socket()
    self.addCleanup(occupied.close)
    occupied.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    occupied.bind(("127.0.0.1", int(ready["base_url"].rsplit(":", 1)[1])))
    occupied.listen()
    self.click("重试启动后端")
    retried = self.state("ready")
    self.assertNotEqual(ready["startup_id"], retried["startup_id"])
    self.assertNotEqual(ready["base_url"], retried["base_url"])
    return retried

  def test_running_sse_survives_page_reload_and_recovers_on_new_port_without_resend(
    self,
  ):
    self.fixture.env["DESKTOP_TEST_RESIDENT_TASK"] = "1"
    host = self.launch()
    self.connect()
    ready = self.state("ready")
    wait_until(lambda: "新建会话开始对话" in self.body())
    self.click("新建")
    self.send("运行中刷新后不重发")
    wait_until(lambda: (self.root / "executing").exists())
    wait_until(lambda: "运行中" in self.body())
    self.instrument_fetch()
    wait_until(lambda: "运行中刷新后不重发" in self.body() and "运行中" in self.body())
    self.set_draft("宿主恢复后保留的草稿\n  缩进")
    self.assertEqual(self.counts(), (1, 1))
    retried = self.kill_and_retry_on_next_port(ready)
    wait_until(
      lambda: "运行中刷新后不重发" in self.body() and "运行失败" in self.body()
    )
    self.assertEqual(
      self.evaluate("document.getElementById('message-draft').value"),
      "宿主恢复后保留的草稿\n  缩进",
    )
    requests = self.evaluate("window.__requests")
    old_streams = [
      r
      for r in requests
      if r["url"].startswith(ready["base_url"]) and r["url"].endswith("/stream")
    ]
    self.assertTrue(old_streams)
    self.assertTrue(all(r["aborted"] for r in old_streams))
    self.assertTrue(all(r["method"] == "GET" for r in requests))
    self.assertTrue(any(r["url"].startswith(retried["base_url"]) for r in requests))
    thread = self.client.get(
      retried["base_url"] + "/api/threads", params={"limit": 20}
    ).json()["data"][0]["id"]
    messages = self.client.get(
      retried["base_url"] + f"/api/threads/{thread}/messages"
    ).json()["data"]
    self.assertEqual(len({m["run_id"] for m in messages}), 1)
    self.assertEqual(sum(m["content"]["type"] == "human" for m in messages), 1)
    self.assertEqual(self.counts(), (1, 2))
    self.record(first=ready, retried=retried, requests=requests, messages=messages)
    self.screenshot()
    self.quit(host)
    self.assertEqual(host.wait(timeout=10), 0)

  def test_late_real_history_cannot_replace_new_startup_thread(self):
    host = self.launch()
    self.connect()
    ready = self.state("ready")
    url = ready["base_url"]
    old_thread = self.client.post(url + "/api/threads").json()["thread_id"]
    self.client.post(
      url + f"/api/threads/{old_thread}/stream",
      json={"message": "旧请求迟到内容"},
      timeout=20,
    ).raise_for_status()
    self.instrument_fetch(hold_messages=True)
    try:
      wait_until(lambda: self.evaluate("Boolean(window.__lateReady)"), timeout=10)
    except AssertionError:
      self.record(
        body=self.body(),
        requests=self.evaluate("window.__requests"),
        held=self.evaluate("window.__held"),
      )
      raise
    new_thread = self.client.post(url + "/api/threads").json()["thread_id"]
    self.client.post(
      url + f"/api/threads/{new_thread}/stream",
      json={"message": "新启动选择的持久事实"},
      timeout=20,
    ).raise_for_status()
    retried = self.kill_and_retry_on_next_port(ready)
    self.select_thread(new_thread)
    wait_until(lambda: "新启动选择的持久事实" in self.body())
    self.evaluate("window.__releaseLate()")
    self.assertNotIn("旧请求迟到内容", self.body())
    self.assertIn("新启动选择的持久事实", self.body())
    self.assertTrue(
      all(r["method"] == "GET" for r in self.evaluate("window.__requests"))
    )
    self.record(
      first=ready,
      retried=retried,
      body=self.body(),
      requests=self.evaluate("window.__requests"),
    )
    self.quit(host)
    self.assertEqual(host.wait(timeout=10), 0)

  def test_replayed_pause_cannot_override_current_resumed_run_status(self):
    self.fixture.env["DESKTOP_TEST_APPROVAL"] = "1"
    host = self.launch()
    self.connect()
    ready = self.state("ready")
    url = ready["base_url"]
    thread = self.client.post(url + "/api/threads").json()["thread_id"]
    response = self.client.post(
      url + f"/api/threads/{thread}/stream",
      json={"message": "需要审批的任务"},
      timeout=20,
    )
    response.raise_for_status()
    frames = [
      json.loads(line[6:])
      for line in response.text.splitlines()
      if line.startswith("data: ")
    ]
    run_id = frames[0]["run_id"]
    required = next(
      frame["payload"] for frame in frames if frame.get("category") == "approval"
    )
    responses = {
      item["id"]: {
        "decisions": [{"type": "approve"} for _ in item["value"]["action_requests"]]
      }
      for item in required["interrupts"]
    }
    with ThreadPoolExecutor(max_workers=1) as pool:
      pending = pool.submit(
        self.client.post,
        url + f"/api/threads/{thread}/runs/{run_id}/approval-decisions",
        json={"responses": responses},
        timeout=30,
      )
      try:
        wait_until(lambda: (self.root / "resumed-executing").exists())
        self.call("Page.reload")
        wait_until(lambda: "需要审批的任务" in self.body())
        self.click("运行详情")
        wait_until(lambda: run_id in self.body())
        # The tool is still blocked: historical interrupted then running must
        # not replace the current metadata snapshot with a stale pause.
        self.assertNotIn("此运行正在等待审批", self.body())
        self.assertIn("运行中", self.body())
        self.record(ready=ready, body=self.body(), run_id=run_id)
      finally:
        (self.root / "continue-task").touch()
        pending.result(timeout=15).raise_for_status()
    wait_until(lambda: "已完成" in self.body())
    self.quit(host)
    self.assertEqual(host.wait(timeout=10), 0)


if __name__ == "__main__":
  unittest.main(verbosity=2)
