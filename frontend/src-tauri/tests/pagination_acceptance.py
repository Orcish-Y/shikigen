"""Real Windows Tauri acceptance for paginated conversation browsing.

Run after frontend/dist and backend_window have been built. This suite uses
the isolated runtime from window_acceptance.py and observes the real WebView
through the existing CDP harness.
"""

import json
import sqlite3
import unittest
from urllib.parse import parse_qs, urlsplit

import win32api
import win32con
from websockets.sync.client import connect
from window_acceptance import REPO, WindowAcceptance, wait_until


class PaginationAcceptance(WindowAcceptance):
  artifact_root = REPO / ".scratch/frontend-completion/ticket-02-native"

  def body(self):
    return self.evaluate("document.body.innerText")

  def connect(self):
    # Tauri/WebView2 may expose an about:blank target before it navigates to
    # Vite. Connecting to that transient target lets navigation close CDP.
    last = None
    stable_polls = 0

    def endpoint():
      nonlocal last, stable_polls
      try:
        targets = self.client.get("http://127.0.0.1:9238/json/list").json()
      except Exception:
        return None
      pages = [
        target
        for target in targets
        if target.get("type") == "page"
        and target.get("url", "").startswith("http://127.0.0.1:5173")
      ]
      if not pages:
        return None
      target = pages[0]
      current = (target.get("id"), target["url"], target["webSocketDebuggerUrl"])
      if current == last:
        stable_polls += 1
      else:
        last = current
        stable_polls = 1
      return target if stable_polls >= 3 else None

    target = wait_until(endpoint)
    self.page_target = {"id": target.get("id"), "url": target["url"]}
    self.ws = connect(target["webSocketDebuggerUrl"], proxy=None)
    wait_until(
      lambda: self.evaluate(
        "document.readyState === 'complete' && Boolean(window.__TAURI_INTERNALS__)"
      ),
      timeout=30,
    )

  def click(self, label):
    self.assertTrue(
      self.evaluate(
        "(() => { const button = [...document.querySelectorAll('button')]"
        f".find(b => b.textContent.trim() === {json.dumps(label)});"
        "if (!button || button.disabled) return false;"
        "button.click(); return true; })()"
      ),
      f"button is missing or disabled: {label}",
    )

  def instrument_fetch(self, hold_first_list=False):
    """Observe public browser traffic and allow one list response to pause."""
    self.call("Page.enable")
    self.call(
      "Page.addScriptToEvaluateOnNewDocument",
      source="""
      window.__paginationRequests = [];
      window.__paginationKeyEvents = [];
      document.addEventListener('keydown', event => {
        if (!window.__capturePaginationKeys
          || !['End', 'PageDown'].includes(event.key)) return;
        const list = document.querySelector('[aria-label="会话列表内容"]');
        const item = {
          key: event.key, code: event.code, repeat: event.repeat,
          isComposing: event.isComposing,
          target: {tagName: event.target.tagName, id: event.target.id,
            ariaLabel: event.target.getAttribute('aria-label')},
          documentHasFocus: document.hasFocus(),
          activeElement: {tagName: document.activeElement.tagName,
            id: document.activeElement.id,
            ariaLabel: document.activeElement.getAttribute('aria-label')},
          list: list && {busy: list.getAttribute('aria-busy'),
            scrollTop: list.scrollTop,
            clientHeight: list.clientHeight, scrollHeight: list.scrollHeight}
        };
        window.__paginationKeyEvents.push(item);
        setTimeout(() => {
          item.defaultPrevented = event.defaultPrevented;
          item.after = {busy: list.getAttribute('aria-busy'), scrollTop: list.scrollTop,
            clientHeight: list.clientHeight, scrollHeight: list.scrollHeight};
        }, 0);
      }, true);
      window.__holdNextThreadList = HOLD_FIRST_LIST;
      const originalFetch = window.fetch.bind(window);
      window.fetch = async (input, init) => {
        const rawUrl = typeof input === 'string' ? input : input.url;
        const url = new URL(rawUrl, location.href);
        const method = init?.method
          ?? (input instanceof Request ? input.method : 'GET');
        const item = {url: url.href, path: url.pathname, method, aborted: false};
        if (url.pathname.startsWith('/api/')) {
          window.__paginationRequests.push(item);
          init?.signal?.addEventListener('abort', () => item.aborted = true);
        }
        const response = await originalFetch(input, init);
        if (url.pathname === '/api/threads' && window.__holdNextThreadList) {
          window.__holdNextThreadList = false;
          const readJson = response.json.bind(response);
          response.json = async () => {
            const data = await readJson();
            window.__heldThreadList = true;
            await new Promise(resolve => window.__releaseThreadList = resolve);
            return data;
          };
        }
        return response;
      };
      """.replace("HOLD_FIRST_LIST", "true" if hold_first_list else "false"),
    )
    self.call("Page.reload")
    wait_until(
      lambda: self.evaluate("Array.isArray(window.__paginationRequests)"), timeout=10
    )

  def browser_requests(self, path=None):
    requests = self.evaluate("window.__paginationRequests") or []
    return (
      requests if path is None else [item for item in requests if item["path"] == path]
    )

  def list_geometry(self):
    return self.evaluate(
      "(() => { const row = document.querySelector('.session');"
      "const skeleton = document.querySelector('.session-skeleton');"
      "const list = document.querySelector('.session-list');"
      "const describe = element => { if (!element) return null;"
      "const rect = element.getBoundingClientRect();"
      "const style = getComputedStyle(element);"
      "return {height: rect.height, marginBottom: style.marginBottom,"
      "lineHeight: style.lineHeight}; };"
      "return {innerWidth: window.innerWidth, innerHeight: window.innerHeight,"
      "devicePixelRatio: window.devicePixelRatio, row: describe(row),"
      "skeleton: describe(skeleton), list: list && {"
      "busy: list.getAttribute('aria-busy'),"
      "scrollTop: list.scrollTop, clientHeight: list.clientHeight,"
      "scrollHeight: list.scrollHeight}}; })()"
    )

  def thread_ids(self):
    return self.evaluate(
      "[...document.querySelectorAll('.session')].map(row => "
      "row.title.split('会话 ID：').pop())"
    )

  def press_list_key(self, key, code, vk, host):
    self.focus_native_window(host)
    self.assertTrue(
      self.evaluate(
        "(() => { const list = document.querySelector('[aria-label=\"会话列表内容\"]');"
        "if (!list || !window.__paginationKeyEvents) return false;"
        "list.focus(); return document.activeElement === list"
        " && document.hasFocus(); })()"
      ),
      "conversation list could not receive keyboard focus in the foreground window",
    )
    before = len(self.evaluate("window.__paginationKeyEvents") or [])
    self.evaluate("window.__capturePaginationKeys = true")
    extended_key = win32con.KEYEVENTF_EXTENDEDKEY
    scan_code = win32api.MapVirtualKey(vk, 0)
    self.assertGreater(scan_code, 0)
    win32api.keybd_event(vk, scan_code, extended_key, 0)
    win32api.keybd_event(vk, scan_code, extended_key | win32con.KEYEVENTF_KEYUP, 0)
    try:
      wait_until(
        lambda: len(self.evaluate("window.__paginationKeyEvents") or []) > before,
        timeout=1,
      )
    except AssertionError:
      pass
    self.evaluate("window.__capturePaginationKeys = false")
    self.last_key_probe = self.evaluate(
      "(() => { const list = document.querySelector('[aria-label=\"会话列表内容\"]');"
      "return {events: window.__paginationKeyEvents,"
      "documentHasFocus: document.hasFocus(),"
      "activeElement: {tagName: document.activeElement.tagName,"
      "id: document.activeElement.id,"
      "ariaLabel: document.activeElement.getAttribute('aria-label')}, after: list && {"
      "busy: list.getAttribute('aria-busy'), scrollTop: list.scrollTop,"
      "clientHeight: list.clientHeight, scrollHeight: list.scrollHeight}}; })()"
    )
    events = self.last_key_probe["events"] or []
    self.assertGreater(
      len(events),
      before,
      f"Win32 {key} did not reach the WebView: {self.last_key_probe}",
    )
    self.assertEqual(events[-1]["key"], key)
    self.assertEqual(events[-1]["code"], code)
    self.assertFalse(events[-1]["repeat"])
    self.assertFalse(events[-1]["isComposing"])

  def seed_threads(self, count):
    """Create real thread rows through HTTP, then freeze a shared sort time."""
    seed_host = self.fixture.host()
    ready = seed_host.state("ready")
    thread_ids = []
    for _ in range(count):
      response = self.client.post(ready["base_url"] + "/api/threads")
      self.assertEqual(response.status_code, 200, response.text)
      thread_ids.append(response.json()["thread_id"])
    seed_host.close()

    timestamp = "2026-10-04T00:00:00+00:00"
    with sqlite3.connect(self.root / "chat.db") as database:
      database.executemany(
        "UPDATE threads SET updated_at = ? WHERE id = ?",
        [(timestamp, thread_id) for thread_id in thread_ids],
      )
      database.commit()
    return thread_ids, timestamp

  def test_real_41_thread_pages_load_only_on_explicit_end_and_preserve_chat(self):
    created_ids, timestamp = self.seed_threads(41)
    host = self.launch()
    try:
      self.connect()
    except Exception:
      debugger_targets = None
      try:
        debugger_targets = self.client.get("http://127.0.0.1:9238/json/list").json()
      except Exception as error:
        debugger_targets = str(error)
      log_path = self.artifacts / "host-0.log"
      self.record(
        stage="connect",
        host_pid=host.pid,
        host_exit_code=host.poll(),
        debugger_targets=debugger_targets,
        host_log=log_path.read_text(encoding="utf-8", errors="replace")
        if log_path.exists()
        else None,
      )
      raise
    ready = self.state("ready")
    base_url = ready["base_url"]

    # Check the actual public HTTP contract from this Tauri-owned runtime.
    first = self.client.get(base_url + "/api/threads", params={"limit": 20})
    self.assertEqual(first.status_code, 200, first.text)
    first_page = first.json()
    self.assertEqual(len(first_page["data"]), 20)
    self.assertIsNotNone(first_page["next_cursor"])
    second = self.client.get(
      base_url + "/api/threads",
      params={"limit": 20, "cursor": first_page["next_cursor"]},
    )
    self.assertEqual(second.status_code, 200, second.text)
    second_page = second.json()
    self.assertEqual(len(second_page["data"]), 20)
    self.assertIsNotNone(second_page["next_cursor"])
    third = self.client.get(
      base_url + "/api/threads",
      params={"limit": 20, "cursor": second_page["next_cursor"]},
    )
    self.assertEqual(third.status_code, 200, third.text)
    third_page = third.json()
    self.assertEqual(len(third_page["data"]), 1)
    self.assertIsNone(third_page["next_cursor"])
    expected_ids = [
      row["id"]
      for page in (first_page, second_page, third_page)
      for row in page["data"]
    ]
    self.assertEqual(set(expected_ids), set(created_ids))
    self.assertEqual(len(expected_ids), len(set(expected_ids)))
    self.assertEqual(
      {
        row["updated_at"]
        for page in (first_page, second_page, third_page)
        for row in page["data"]
      },
      {timestamp},
    )

    self.instrument_fetch(hold_first_list=True)
    try:
      wait_until(lambda: self.evaluate("window.__heldThreadList === true"), timeout=10)
      skeleton_geometry = self.list_geometry()
      self.assertIsNotNone(skeleton_geometry["skeleton"])
      self.assertIsNone(skeleton_geometry["row"])
      self.evaluate("window.__releaseThreadList()")
      wait_until(lambda: len(self.thread_ids() or []) == 20, timeout=15)
      wait_until(
        lambda: self.evaluate(
          "document.querySelector('.session-list')"
          "?.getAttribute('aria-busy') !== 'true'"
        ),
        timeout=10,
      )
      row_geometry = self.list_geometry()
      self.assertEqual(
        self.thread_ids(),
        [row["id"] for row in first_page["data"]],
        "the WebView's first page must match the HTTP ordering",
      )
      self.assertIn("仅筛选已加载会话", self.body())
      self.assertFalse(
        self.evaluate(
          "[...document.querySelectorAll('button')].some(button => "
          "button.textContent.trim() === '加载更多')"
        ),
        "normal pagination must not expose a load-more button",
      )

      wait_until(
        lambda: self.evaluate(
          "Boolean(document.querySelector('.session[aria-current=true]'))"
        ),
        timeout=10,
      )
      self.evaluate(
        "(() => { const input = document.getElementById('message-draft');"
        "Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')"
        ".set.call(input, '分页期间保留的草稿');"
        "input.dispatchEvent(new Event('input', {bubbles:true})); })()"
      )
      active_before = self.evaluate(
        "document.querySelector('.session[aria-current=true]')?.title"
      )
      chat_requests_before = self.browser_requests("/api/threads")
      messages_before = self.browser_requests()
      chat_io_before = [
        item
        for item in messages_before
        if item["path"].endswith("/messages") or item["path"].endswith("/stream")
      ]

      self.press_list_key("End", "End", 35, host)
      wait_until(lambda: len(self.thread_ids() or []) == 40, timeout=15)
      self.assertEqual(
        self.thread_ids(),
        [row["id"] for row in first_page["data"] + second_page["data"]],
      )
      self.assertNotIn("没有更多", self.body())

      self.press_list_key("End", "End", 35, host)
      wait_until(lambda: len(self.thread_ids() or []) == 41, timeout=15)
      self.assertEqual(self.thread_ids(), expected_ids)
      wait_until(lambda: "没有更多" in self.body())
      cursors = [
        parse_qs(urlsplit(item["url"]).query).get("cursor", [None])[0]
        for item in self.browser_requests("/api/threads")
        if parse_qs(urlsplit(item["url"]).query).get("cursor")
      ]
      self.assertEqual(cursors, [first_page["next_cursor"], second_page["next_cursor"]])
      self.assertEqual(
        [
          item
          for item in self.browser_requests()
          if item["path"].endswith("/messages") or item["path"].endswith("/stream")
        ],
        chat_io_before,
        "pagination must not reread chat history or start an SSE stream",
      )
      self.assertEqual(
        self.evaluate("document.querySelector('.session[aria-current=true]')?.title"),
        active_before,
        "pagination must keep the selected conversation",
      )
      self.assertEqual(
        self.evaluate("document.getElementById('message-draft').value"),
        "分页期间保留的草稿",
      )

      # A delayed explicit list reload keeps existing rows and chat state while
      # issuing only GET /api/threads, without reopening the selected thread.
      self.assertTrue(
        self.evaluate(
          "(() => { window.__holdNextThreadList = true;"
          "const button = [...document.querySelectorAll('button')]"
          ".find(item => item.textContent.trim() === '重载列表');"
          "if (!button || button.disabled) return false;"
          "button.click(); return true; })()"
        )
      )
      wait_until(lambda: self.evaluate("window.__heldThreadList === true"), timeout=10)
      self.assertNotIn("正在刷新会话列表", self.body())
      self.assertTrue(
        self.evaluate(
          "Boolean(document.querySelector('.list-scope button[aria-busy=true] .list-reload-spinner'))"
        )
      )
      self.assertTrue(
        self.evaluate(
          "document.querySelector('.session-list')"
          "?.getAttribute('aria-busy') === 'true'"
        )
      )
      self.assertEqual(len(self.thread_ids()), 41)
      self.assertEqual(
        self.evaluate("document.getElementById('message-draft').value"),
        "分页期间保留的草稿",
      )
      self.assertEqual(
        [
          item
          for item in self.browser_requests()
          if item["path"].endswith("/messages") or item["path"].endswith("/stream")
        ],
        chat_io_before,
      )
      list_count_before_release = len(self.browser_requests("/api/threads"))
      self.evaluate("window.__releaseThreadList()")
      wait_until(
        lambda: (
          not self.evaluate(
            "document.querySelector('.session-list')"
            "?.getAttribute('aria-busy') === 'true'"
          )
        ),
        timeout=10,
      )
      self.assertEqual(
        len(self.browser_requests("/api/threads")), list_count_before_release
      )
      self.assertEqual(len(self.thread_ids()), 41)

      self.assertFalse(
        self.evaluate("Boolean(document.querySelector('.list-reload-spinner'))")
      )
      self.record(
        ready=ready,
        timestamp=timestamp,
        page_sizes=[
          len(page["data"]) for page in (first_page, second_page, third_page)
        ],
        page_ids=expected_ids,
        browser_requests=self.browser_requests(),
        active=active_before,
        draft=self.evaluate("document.getElementById('message-draft').value"),
        page_target=self.page_target,
        skeleton_geometry=skeleton_geometry,
        row_geometry=row_geometry,
        last_key_probe=getattr(self, "last_key_probe", None),
      )
      self.screenshot()
    except Exception:
      self.record(
        ready=ready,
        body=self.body(),
        page_ids=self.thread_ids(),
        browser_requests=self.browser_requests(),
        skeleton_geometry=locals().get("skeleton_geometry"),
        row_geometry=self.list_geometry(),
        last_key_probe=getattr(self, "last_key_probe", None),
      )
      self.screenshot()
      raise


if __name__ == "__main__":
  unittest.main(verbosity=2)
