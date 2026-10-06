"""Ticket 20: real Tauri, public requests, persistent titles and input focus."""

import json
import sqlite3

import win32con
import win32gui
from message_drafts_acceptance import MessageDraftAcceptance
from pagination_acceptance import PaginationAcceptance
from window_acceptance import REPO, wait_until


class ConversationPresentationAcceptance(MessageDraftAcceptance):
  artifact_root = REPO / ".scratch/frontend-completion/ticket-20/native"
  connect = PaginationAcceptance.connect
  seed_threads = PaginationAcceptance.seed_threads

  def instrument_presentation(self, extra_script=""):
    self.call("Page.enable")
    self.call(
      "Page.addScriptToEvaluateOnNewDocument",
      source="""
            (()=>{
            window.__presentationRequests=[];
            const fetchFromBackend=window.fetch.bind(window);
            window.fetch=async (input,init)=>{
              const url=new URL(typeof input==='string'?input:input.url,location.href);
              const request={path:url.pathname,method:init?.method??'GET'};
              if(url.pathname.startsWith('/api/'))window.__presentationRequests.push(request);
              if(url.pathname.endsWith('/messages')&&window.__failHistory)
                return Response.json({detail:'测试公开历史不可读'},{status:500});
              const response=await fetchFromBackend(input,init);
              if(url.pathname===`/api/threads/${window.__holdThreadId}/messages`){
                window.__holdThreadId=null;
                await new Promise(resolve=>window.__releaseHistory=resolve);
              }
              return response;
            };
            """
      + extra_script
      + "})();",
    )
    self.call("Page.reload")
    wait_until(lambda: self.evaluate("Array.isArray(window.__presentationRequests)"))

  def title(self):
    return self.evaluate("document.querySelector('.chat-toolbar h1')?.textContent")

  def selected_thread(self):
    return self.evaluate(
      "document.querySelector('.session[aria-current=true]')?.dataset.conversationId"
    )

  def select_thread(self, thread_id):
    self.assertTrue(
      self.evaluate(
        "(() => {const row=[...document.querySelectorAll('.session')]"
        f".find(row=>row.dataset.conversationId==={json.dumps(thread_id)});"
        "if(!row)return false;row.click();return true;})()"
      )
    )

  def inspect_current(self):
    self.call("Page.bringToFront")
    self.assertTrue(
      self.evaluate(
        "(() => {const button=document.querySelector('.session[aria-current=true]')"
        ".parentElement.querySelector('.session-inspect');button.focus();"
        "return document.activeElement===button;})()"
      )
    )
    self.call(
      "Input.dispatchKeyEvent",
      type="keyDown",
      key="Enter",
      code="Enter",
      text="\r",
      unmodifiedText="\r",
      windowsVirtualKeyCode=13,
    )
    self.call(
      "Input.dispatchKeyEvent",
      type="keyUp",
      key="Enter",
      code="Enter",
      windowsVirtualKeyCode=13,
    )
    wait_until(lambda: self.evaluate("Boolean(document.querySelector('dialog[open]'))"))

  def capture_presentation(self, **evidence):
    self.record(
      requests=self.evaluate("window.__presentationRequests"),
      page_target=self.page_target,
      title=self.title(),
      draft=self.draft(),
      body=self.body(),
      **evidence,
    )
    self.screenshot()

  def close_overlay(self):
    self.assertTrue(
      self.evaluate(
        "(() => {const selector='dialog[open] button[aria-label=关闭]';"
        "const button=document.querySelector(selector);"
        "if(!button)return false;button.click();return true;})()"
      )
    )
    wait_until(lambda: self.evaluate("!document.querySelector('dialog[open]')"))

  def test_committed_title_formal_override_filter_full_view_and_utc(self):
    host, ready, thread = self.start_empty()
    self.instrument_presentation()
    wait_until(lambda: "从一个想法开始" in self.body())
    original = "  第一条中文任务\n    保留缩进与正文  \n"
    expected = "第一条中文任务 保留缩进与正文"
    self.send(original)
    wait_until(lambda: self.title() == expected)
    wait_until(lambda: "已完成" in self.body())
    self.assertEqual(self.users(ready, thread)[0]["content"]["content"], original)
    draft = "  下一条\n  不丢草稿  "
    self.set_draft(draft)
    formal_title = "正式会话标题 · " + "完整内容不能被截断丢弃" * 12
    with sqlite3.connect(self.root / "chat.db") as database:
      database.execute("UPDATE threads SET title=? WHERE id=?", (formal_title, thread))
    self.click("重载列表")
    wait_until(lambda: self.title() == formal_title)
    self.evaluate("document.querySelector('.search input').focus()")
    self.call("Input.insertText", text="完整内容不能")
    self.assertEqual(self.evaluate("document.querySelectorAll('.session').length"), 1)
    self.inspect_current()
    self.assertIn(
      formal_title, self.evaluate("document.querySelector('dialog').innerText")
    )
    self.assertIn(
      "Asia/Shanghai", self.evaluate("document.querySelector('dialog').innerText")
    )
    self.assertIn("UTC：", self.evaluate("document.querySelector('dialog').innerText"))
    self.evaluate(
      "window.__copiedText=null;"
      "navigator.clipboard.writeText=async text=>window.__copiedText=text"
    )
    self.click("复制更新时间 UTC")
    copied_utc = self.evaluate("window.__copiedText")
    public_thread = self.client.get(
      ready["base_url"] + "/api/threads", params={"limit": 20}
    ).json()["data"][0]
    self.assertEqual(copied_utc, public_thread["updated_at"])
    self.click("复制完整本地时间")
    copied_local_time = self.evaluate("window.__copiedText")
    self.assertEqual(
      copied_local_time,
      self.evaluate(
        "document.querySelector('.conversation-identity section:last-child p')"
        ".textContent"
      ),
    )
    self.screenshot()
    (self.artifacts / "identity.png").write_bytes(
      (self.artifacts / "window.png").read_bytes()
    )
    self.close_overlay()
    self.assertTrue(
      self.evaluate("document.activeElement.classList.contains('session-inspect')")
    )
    self.evaluate(
      "(() => {const input=document.querySelector('.search input');"
      "Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,'');"
      "input.dispatchEvent(new Event('input',{bubbles:true}));})()"
    )
    with sqlite3.connect(self.root / "chat.db") as database:
      database.execute("UPDATE threads SET title=NULL WHERE id=?", (thread,))
    self.click("重载列表")
    wait_until(lambda: self.title() == expected)
    self.assertEqual(self.draft(), draft)
    requests = self.evaluate("window.__presentationRequests")
    self.assertFalse(any(request["method"] == "PATCH" for request in requests))
    run_id = self.users(ready, thread)[0]["run_id"]
    expected_message_paths = {
      f"/api/threads/{thread}/messages",
      f"/api/threads/{thread}/runs/{run_id}/messages",
    }
    self.assertTrue(
      all(
        request["path"] in expected_message_paths
        for request in requests
        if request["path"].endswith("/messages")
      )
    )
    self.capture_presentation(
      original=original,
      expected=expected,
      formal_title=formal_title,
      copied_utc=copied_utc,
      copied_local_time=copied_local_time,
      clipboard_scope="public clipboard stub, not OS clipboard",
    )
    self.quit(host)
    self.assertEqual(host.wait(timeout=15), 0)

  def test_native_restart_revalidates_cache_failed_read_and_storage_failure_keep_memory(
    self,
  ):
    host, ready, thread = self.start_empty()
    original = "重启后从已提交正文核对标题"
    self.send(original)
    wait_until(lambda: self.title() == original)
    wait_until(lambda: "已完成" in self.body())
    self.set_draft("重启保留原文\n  缩进")
    cache = self.evaluate(
      "JSON.parse(localStorage.getItem('shikigen.conversation-titles.v1'))"
    )
    self.evaluate(
      "(() => {const key='shikigen.conversation-titles.v1';"
      "const cache=JSON.parse(localStorage.getItem(key));"
      "cache.titles[0][1].title='过时缓存标题';"
      "localStorage.setItem('shikigen.conversation-titles.v1',JSON.stringify(cache));})()"
    )
    self.quit(host)
    self.assertEqual(host.wait(timeout=15), 0)
    self.ws.close()
    self.ws = None
    reopened_host = self.launch()
    self.connect()
    reopened_ready = self.state("ready")
    wait_until(lambda: self.title() == original)
    self.assertEqual(self.draft(), "重启保留原文\n  缩进")
    actual_cache = self.evaluate(
      "JSON.parse(localStorage.getItem('shikigen.conversation-titles.v1'))"
    )
    self.assertEqual(actual_cache["titles"][0][1]["title"], original)
    self.instrument_presentation("window.__failHistory=true;")
    wait_until(lambda: "会话历史读取失败" in self.body())
    self.assertEqual(self.title(), original)
    self.assertNotIn("从一个想法开始", self.body())
    self.evaluate("window.__failHistory=false")
    self.click("刷新数据")
    wait_until(lambda: "会话历史读取失败" not in self.body())
    self.evaluate("localStorage.removeItem('shikigen.conversation-titles.v1')")
    self.instrument_presentation("""
          window.__failHistory=false;
          const saveLocalValue=Storage.prototype.setItem;
          Storage.prototype.setItem=function(key,value){
            if(key==='shikigen.conversation-titles.v1')
              throw new Error('测试标题存储失败');
            return saveLocalValue.call(this,key,value);
          };
        """)
    wait_until(lambda: "本地标题保存不可用" in self.body())
    self.assertEqual(self.title(), original)
    self.assertEqual(self.draft(), "重启保留原文\n  缩进")
    self.assertEqual(len(self.users(reopened_ready, thread)), 1)
    self.assertIn("草稿在本地保存，重启后保留", self.body())
    self.assertNotIn("草稿仅在本次应用中保留", self.body())
    self.capture_presentation(
      initial_cache=cache, revalidated_cache=actual_cache, thread=thread, restarted=True
    )
    self.quit(reopened_host)
    self.assertEqual(reopened_host.wait(timeout=15), 0)

  def test_examples_append_and_late_history_does_not_steal_input_or_modal_focus(self):
    host, ready, first_thread = self.start_empty()
    self.instrument_presentation()
    wait_until(lambda: "从一个想法开始" in self.body())
    original = "  已有草稿\n    缩进  \n"
    self.set_draft(original)
    expected = original
    for example in (
      "解释当前项目的目录结构",
      "搜索项目中的工具注册逻辑",
      "总结一个指定网页的内容",
    ):
      self.click(example)
      expected += "\n\n" + example
      self.assertEqual(self.draft(), expected)
      self.assertEqual(self.evaluate("document.activeElement.id"), "message-draft")
    self.assertEqual(len(self.users(ready, first_thread)), 0)
    self.assertEqual(self.title(), "新会话")
    self.click("新建")
    wait_until(lambda: self.selected_thread() != first_thread)
    second_thread = self.selected_thread()
    wait_until(lambda: "从一个想法开始" in self.body())
    self.click("解释当前项目的目录结构")
    self.assertEqual(self.draft(), "解释当前项目的目录结构")
    self.evaluate(f"window.__holdThreadId={json.dumps(first_thread)}")
    self.select_thread(first_thread)
    wait_until(lambda: self.evaluate("Boolean(window.__releaseHistory)"))
    self.assertNotIn("从一个想法开始", self.body())
    self.evaluate("document.querySelector('button[aria-label=打开命令面板]').click()")
    wait_until(lambda: self.evaluate("Boolean(document.querySelector('dialog[open]'))"))
    self.evaluate(
      "document.querySelector('dialog button').focus();"
      "window.__modalFocus=document.activeElement;true"
    )
    self.evaluate("window.__releaseHistory();window.__releaseHistory=null")
    wait_until(lambda: "从一个想法开始" in self.body())
    self.assertTrue(self.evaluate("document.activeElement===window.__modalFocus"))
    self.close_overlay()
    self.select_thread(second_thread)
    wait_until(lambda: "从一个想法开始" in self.body())
    self.evaluate(f"window.__holdThreadId={json.dumps(first_thread)}")
    self.select_thread(first_thread)
    wait_until(lambda: self.evaluate("Boolean(window.__releaseHistory)"))
    self.select_thread(second_thread)
    self.set_draft("另一会话正在输入")
    self.evaluate("window.__releaseHistory();window.__releaseHistory=null")
    self.assertEqual(self.draft(), "另一会话正在输入")
    self.assertEqual(self.selected_thread(), second_thread)
    self.assertEqual(self.evaluate("document.activeElement.id"), "message-draft")
    self.select_thread(first_thread)
    wait_until(lambda: "从一个想法开始" in self.body())
    self.assertEqual(self.draft(), expected)
    self.assertFalse(
      any(
        request["method"] == "POST" and request["path"].endswith("/stream")
        for request in self.evaluate("window.__presentationRequests")
      )
    )
    self.capture_presentation(
      original=original,
      appended=expected,
      first_thread=first_thread,
      second_thread=second_thread,
    )
    self.quit(host)
    self.assertEqual(host.wait(timeout=15), 0)

  def test_calendar_minute_and_midnight_refresh_is_display_only(self):
    thread_ids, _ = self.seed_threads(4)
    timestamps = (
      "2026-10-06T15:59:00.123456+00:00",
      "2026-10-05T02:00:00+00:00",
      "2026-09-28T02:00:00+00:00",
      "2026-10-08T02:00:00+00:00",
    )
    with sqlite3.connect(self.root / "chat.db") as database:
      database.executemany(
        "UPDATE threads SET title=?,updated_at=? WHERE id=?",
        [
          (f"日期示例{index}", timestamp, thread_id)
          for index, (thread_id, timestamp) in enumerate(
            zip(thread_ids, timestamps, strict=True)
          )
        ],
      )
    host = self.launch()
    self.connect()
    self.state("ready")
    self.call("Emulation.setTimezoneOverride", timezoneId="Asia/Shanghai")
    self.instrument_presentation("""
          window.__displayNow=Date.parse('2026-10-06T15:59:10Z');
          Date.now=()=>window.__displayNow;
          const scheduleDelay=window.setTimeout.bind(window);
          const cancelDelay=window.clearTimeout.bind(window);
          window.__clockId=-1;
          window.setTimeout=(onTimeout,delay,...args)=>{
            if(delay===60000-window.__displayNow%60000){
              const id=--window.__clockId;
              window.__displayTimer={id,onTimeout};return id;
            }
            return scheduleDelay(onTimeout,delay,...args);
          };
          window.clearTimeout=id=>{
            if(window.__displayTimer?.id===id)window.__displayTimer=null;
            else cancelDelay(id);
          };
          window.__advanceDisplayClock=()=>{
            const timer=window.__displayTimer;window.__displayTimer=null;
            window.__displayNow=Date.parse('2026-10-06T16:00:00.123456Z');timer.onTimeout();
          };
        """)
    wait_until(
      lambda: self.evaluate("document.querySelectorAll('.session').length===4")
    )
    initial_groups = self.evaluate(
      "[...document.querySelectorAll('.group-label')].map(label=>label.textContent)"
    )
    self.assertEqual(initial_groups, ["今天", "昨天", "更早", "日期待确认"])
    order = self.evaluate(
      "[...document.querySelectorAll('.session')].map(row=>row.dataset.conversationId)"
    )
    before_requests = self.evaluate("window.__presentationRequests.length")
    self.evaluate("window.__advanceDisplayClock()")
    wait_until(
      lambda: self.evaluate(
        "[...document.querySelectorAll('.group-label')].every(label=>label.textContent!=='今天')"
      )
    )
    self.assertIn("1 分钟前", self.body())
    self.assertEqual(
      self.evaluate("window.__presentationRequests.length"), before_requests
    )
    # Grouping moves rows without changing their timestamp or identity.
    actual_thread = self.evaluate(
      "[...document.querySelectorAll('.session')].find(row=>row.innerText.includes('日期示例0'))?.dataset.conversationId"
    )
    self.assertEqual(actual_thread, thread_ids[0])
    hwnd = self.window(host)
    win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
    wait_until(lambda: not win32gui.IsWindowVisible(hwnd))
    wait_until(lambda: self.evaluate("window.__displayTimer===null"))
    self.evaluate("window.__displayNow=Date.parse('2026-10-14T12:00:00Z')")
    frozen_requests = self.evaluate("window.__presentationRequests.length")
    self.tray_menu(host, "打开主窗口", native_command=True)
    wait_until(lambda: win32gui.IsWindowVisible(hwnd))
    wait_until(lambda: self.evaluate("Boolean(window.__displayTimer)"))
    wait_until(lambda: "2026/10/06" in self.body())
    # The established visibility path makes its one list and selected-history read.
    # The separate display refresh adds neither history reads nor a second list poll.
    wait_until(
      lambda: (
        self.evaluate("window.__presentationRequests.length") >= frozen_requests + 2
      )
    )
    restored_requests = self.evaluate("window.__presentationRequests")[frozen_requests:]
    self.assertEqual(len(restored_requests), 2)
    self.assertTrue(all(request["method"] == "GET" for request in restored_requests))
    self.capture_presentation(
      initial_groups=initial_groups,
      initial_visual_order=order,
      timestamps=timestamps,
      clock_scope="public page virtual wall-clock minute",
    )
    self.quit(host)
    self.assertEqual(host.wait(timeout=15), 0)
