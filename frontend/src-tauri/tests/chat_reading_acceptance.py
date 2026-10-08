"""第 09 票：真实 Tauri、公开 HTTP/SSE、原生显隐/恢复及浏览器布局边界。"""

import json
import time
import unittest

import win32con
import win32gui
from message_drafts_acceptance import MessageDraftAcceptance
from window_acceptance import REPO, wait_until


class ChatReadingAcceptance(MessageDraftAcceptance):
  artifact_root = REPO / ".scratch/frontend-completion/ticket-09/native"

  def setUp(self):
    super().setUp()
    bootstrap = self.root / "app/desktop.py"
    bootstrap.write_text(
      bootstrap.read_text(encoding="utf-8").replace(
        "from runtime_fixtures import deterministic_agent",
        "from desktop_reading_fixtures import reading_agent as deterministic_agent",
      ),
      encoding="utf-8",
    )

  def geometry(self):
    return self.evaluate("""(() => {
      const t=document.querySelector('.timeline');
      if (!t) return null;
      const top=t.getBoundingClientRect().top;
      const anchors=[...t.querySelectorAll('[data-reading-anchor]')]
        .filter(e=>e.getClientRects().length);
      const a=anchors.filter(e=>e.getBoundingClientRect().top<=top+1).at(-1)
        ?? anchors[0];
      return {scrollTop:t.scrollTop, height:t.clientHeight, total:t.scrollHeight,
        id:a?.dataset.readingAnchor, offset:a?.getBoundingClientRect().top-top,
        following:!document.querySelector('.reading-controls'),
        newContent:document.querySelector('.reading-controls')?.textContent.includes('有新内容')??false};
    })()""")

  def at_latest(self):
    value = self.geometry()
    return (
      value
      and value["following"]
      and abs(value["total"] - value["height"] - value["scrollTop"]) <= 2
    )

  def home(self):
    self.evaluate("document.querySelector('.timeline').focus({preventScroll:true})")
    self.call(
      "Input.dispatchKeyEvent",
      type="keyDown",
      key="Home",
      code="Home",
      windowsVirtualKeyCode=36,
    )
    self.call(
      "Input.dispatchKeyEvent",
      type="keyUp",
      key="Home",
      code="Home",
      windowsVirtualKeyCode=36,
    )
    wait_until(lambda: not self.geometry()["following"])
    wait_until(lambda: self.geometry()["scrollTop"] <= 1)

  def pause_at(self, selector):
    self.home()
    self.evaluate(
      "(() => {const t=document.querySelector('.timeline'); const a="
      f"document.querySelector({json.dumps(selector)});"
      "t.scrollTop+=a.getBoundingClientRect().top-t.getBoundingClientRect().top+16;})()"
    )
    wait_until(lambda: self.geometry()["scrollTop"] > 100)
    return self.geometry()

  def assert_anchor(self, expected):
    def match():
      actual = self.geometry()
      return (
        actual
        and actual["id"] == expected["id"]
        and abs(actual["offset"] - expected["offset"]) <= 2
        and not actual["following"]
      )

    wait_until(match, timeout=10)
    self.assertTrue(match(), self.geometry())

  def complete(self):
    (self.root / "allow-reading-stream").touch()
    wait_until(
      lambda: (
        self.evaluate("document.querySelector('.toolbar-badge').textContent")
        == "已完成"
      )
    )
    wait_until(lambda: self.at_latest())

  def test_scrollbar_drag_and_hold_preserve_reading_position(self):
    (self.root / "allow-reading-stream").touch()
    host, ready, thread = self.start_empty()
    self.send("滚动条拖动的长会话")
    self.complete()
    scrollbar = self.evaluate("""(() => {
      const t=document.querySelector('.timeline'), r=t.getBoundingClientRect();
      const thumb=Math.max(20, t.clientHeight*t.clientHeight/t.scrollHeight);
      return {x:r.right-5, y:r.bottom-thumb/2, destination:r.top+r.height/2};
    })()""")
    self.call("Input.dispatchMouseEvent", type="mousePressed",
      x=scrollbar["x"], y=scrollbar["y"], button="left", buttons=1, clickCount=1)
    try:
      # Native scrollbar dragging must outlive the old one-second input window.
      time.sleep(1.2)
      self.call("Input.dispatchMouseEvent", type="mouseMoved",
        x=scrollbar["x"], y=scrollbar["destination"], button="left", buttons=1)
      time.sleep(0.2)
      dragged = self.geometry()
      self.assertFalse(dragged["following"], dragged)
      self.assertGreater(dragged["scrollTop"], 20)
      self.assertLess(dragged["scrollTop"], dragged["total"]-dragged["height"]-20)
      # Sample throughout the hold, rather than only checking the final frame.
      samples = []
      for _ in range(15):
        time.sleep(0.1)
        samples.append(self.geometry())
        self.assertAlmostEqual(samples[-1]["scrollTop"], dragged["scrollTop"], delta=2)
        self.assertFalse(samples[-1]["following"])
    finally:
      self.call("Input.dispatchMouseEvent", type="mouseReleased",
        x=scrollbar["x"], y=scrollbar["destination"], button="left", buttons=0,
        clickCount=1)
    time.sleep(1.2)
    self.assert_anchor(dragged)
    self.record(ready=ready, thread=thread, dragged=dragged, samples=samples,
      released=self.geometry())
    self.screenshot()
    self.click("回到底部")
    wait_until(self.at_latest)
    self.quit(host)
    self.assertEqual(host.wait(timeout=15), 0)

  def test_switch_hide_host_reentry_and_restart_preserve_reading_intent(self):
    (self.root / "allow-reading-stream").touch()
    host, ready, thread = self.start_empty()
    self.send("首个长会话")
    self.complete()
    saved = self.pause_at("article.message.assistant:last-of-type")
    self.set_draft("阅读草稿保留")
    self.click("新建")
    wait_until(lambda: "从一个想法开始" in self.body())
    other = self.evaluate(
      "document.querySelector('.session[aria-current=true]').title"
    ).split("会话 ID：")[-1]
    self.select_thread(thread)
    self.assert_anchor(saved)
    self.click("刷新数据")
    self.assert_anchor(saved)
    hwnd = self.window(host)
    win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
    wait_until(lambda: not win32gui.IsWindowVisible(hwnd))
    wait_until(
      lambda: (
        not self.evaluate(
          "window.__TAURI_INTERNALS__.invoke('get_workspace_visibility')"
        )["visible"]
      )
    )
    self.tray_menu(host, "打开主窗口", native_command=True)
    wait_until(lambda: win32gui.IsWindowVisible(hwnd))
    self.assert_anchor(saved)
    retried = self.kill_and_retry_on_next_port(ready)
    wait_until(lambda: self.geometry() and "阅读完成" in self.body())
    self.assert_anchor(saved)
    self.assertEqual(self.draft(), "阅读草稿保留")
    history = self.client.get(
      retried["base_url"] + f"/api/threads/{thread}/messages"
    ).json()["data"]
    self.assertEqual(sum(m["content"]["type"] == "human" for m in history), 1)
    self.screenshot()
    restored = self.geometry()
    self.quit(host)
    self.assertEqual(host.wait(timeout=15), 0)
    self.ws.close()
    self.ws = None
    second = self.launch()
    self.connect()
    reopened = self.state("ready")
    wait_until(lambda: "阅读完成" in self.body() and self.at_latest())
    self.record(
      thread=thread,
      other=other,
      ready=ready,
      retried=retried,
      reopened=reopened,
      saved=saved,
      restored=restored,
      restart=self.geometry(),
      history=history,
    )
    self.quit(second)
    self.assertEqual(second.wait(timeout=15), 0)

  def test_accepted_send_stream_replacement_layout_and_internal_scroll(self):
    (self.root / "allow-reading-stream").touch()
    host, ready, thread = self.start_empty()
    self.send("已有长历史")
    self.complete()
    self.home()
    original = self.geometry()
    (self.root / "allow-reading-stream").unlink()
    self.evaluate("window.__delayAcceptance=true")
    self.send("新的流式回答")
    wait_until(lambda: self.evaluate("Boolean(window.__releaseAcceptance)"))
    self.assert_anchor(original)
    self.evaluate("window.__releaseAcceptance()")
    wait_until(lambda: self.at_latest() and "生成中" in self.body())
    self.home()
    reading = self.geometry()
    (self.root / "allow-reading-stream").touch()
    wait_until(
      lambda: (
        self.evaluate("document.querySelector('.toolbar-badge').textContent")
        == "已完成"
      )
    )
    self.assert_anchor(reading)
    self.assertTrue(self.geometry()["newContent"])
    self.click("回到底部")
    wait_until(self.at_latest)
    # 最新模式时代码区滚轮不能关闭主时间线跟随。
    rect = self.evaluate(
      "(() => {const pre=[...document.querySelectorAll('.content-block pre')]"
      ".filter(p=>!p.closest('details:not([open]),[hidden]')"
      " && p.getClientRects().length).at(-1);window.__readingCode=pre;"
      "const r=pre.getBoundingClientRect(); const x=r.x+20,y=r.y+20;"
      "return {x,y,hit:pre.contains(document.elementFromPoint(x,y))};})()"
    )
    self.assertTrue(rect["hit"], rect)
    self.call(
      "Input.dispatchMouseEvent",
      type="mouseWheel",
      x=rect["x"],
      y=rect["y"],
      deltaX=0,
      deltaY=120,
    )
    wait_until(lambda: self.evaluate("window.__readingCode.scrollTop") > 0)
    self.assertTrue(self.geometry()["following"])
    self.call(
      "Input.dispatchMouseEvent",
      type="mouseWheel",
      x=rect["x"],
      y=rect["y"],
      deltaX=0,
      deltaY=-120,
    )
    self.assertTrue(self.geometry()["following"])
    saved = self.pause_at("article.message.assistant:last-of-type")
    # 浏览器布局边界：注入本地 data 图片模拟图片异步增高；本地资源接口归 14 票。
    self.evaluate("""(() => {
      const a=document.querySelector('article.message.assistant:last-of-type');
      const image=document.createElement('img'); image.id='reading-height-fixture';
      image.style.cssText='display:block;width:160px;height:1px';
      image.src='data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg"'
        +' width="160" height="160"></svg>';
      a.before(image); setTimeout(()=>image.style.height='160px',80);
    })()""")
    wait_until(
      lambda: (
        self.evaluate("document.getElementById('reading-height-fixture').clientHeight")
        == 160
      )
    )
    self.assert_anchor(saved)
    self.evaluate("document.querySelector('.tool-summary').click()")
    self.assert_anchor(saved)
    self.call(
      "Emulation.setDeviceMetricsOverride",
      width=390,
      height=780,
      deviceScaleFactor=1,
      mobile=False,
    )
    self.assert_anchor(saved)
    self.call("Emulation.clearDeviceMetricsOverride")
    self.assert_anchor(saved)
    self.click("刷新数据")
    self.assert_anchor(saved)
    self.assertFalse(self.geometry()["newContent"])
    self.evaluate("document.querySelector('.timeline').focus({preventScroll:true})")
    self.call(
      "Input.dispatchKeyEvent",
      type="keyDown",
      key="End",
      code="End",
      windowsVirtualKeyCode=35,
    )
    self.call(
      "Input.dispatchKeyEvent",
      type="keyUp",
      key="End",
      code="End",
      windowsVirtualKeyCode=35,
    )
    wait_until(self.at_latest)
    history = self.client.get(
      ready["base_url"] + f"/api/threads/{thread}/messages"
    ).json()["data"]
    self.assertEqual(sum(m["content"]["type"] == "human" for m in history), 2)
    self.assertEqual(self.evaluate("window.__sends.length"), 2)
    self.record(
      ready=ready,
      thread=thread,
      initial=original,
      streaming=reading,
      anchored=saved,
      latest=self.geometry(),
      history=history,
      requests=self.evaluate("window.__sends"),
    )
    self.screenshot()
    self.quit(host)
    self.assertEqual(host.wait(timeout=15), 0)

  def test_only_active_approval_action_locates_and_focuses_timeline_card(self):
    self.fixture.env["DESKTOP_TEST_READING_APPROVAL"] = "1"
    host, ready, thread = self.start_empty()
    self.send("等待审批时保护阅读")
    wait_until(lambda: "生成中" in self.body() and self.at_latest())
    self.home()
    saved = self.geometry()
    (self.root / "allow-reading-stream").touch()
    wait_until(
      lambda: (
        self.evaluate("document.querySelector('.toolbar-badge').textContent")
        == "等待审批"
      )
    )
    self.assert_anchor(saved)
    # 现有审批契约先GET核实；POST到达的请求不是已核实的审批操作资格。
    self.click("刷新数据")
    wait_until(lambda: "审批请求已核实，等待处理。" in self.body())
    self.assert_anchor(saved)
    self.click("处理审批")
    wait_until(
      lambda: self.evaluate("document.activeElement.id") == "current-approval-status"
    )
    self.assertFalse(self.geometry()["following"])
    self.assertTrue(
      self.evaluate(
        "(() => {const t=document.querySelector('.timeline').getBoundingClientRect();"
        "const a=document.getElementById('current-approval-status')"
        ".getBoundingClientRect();return a.top>=t.top-1 && a.bottom<=t.bottom+1})()"
      )
    )
    self.click("运行详情")
    position = self.geometry()
    self.evaluate(
      "document.querySelector('dialog[open] .details-content').scrollTop=200"
    )
    self.assertEqual(self.geometry(), position)
    self.evaluate("document.querySelector('dialog[open] [aria-label=关闭]').click()")
    self.assertEqual(self.evaluate("window.__sends.length"), 1)
    self.record(
      ready=ready,
      thread=thread,
      saved=saved,
      located=self.geometry(),
      requests=self.evaluate("window.__sends"),
    )
    self.screenshot()
    self.quit(host)
    self.assertEqual(host.wait(timeout=15), 0)


if __name__ == "__main__":
  suite = unittest.TestSuite(
    ChatReadingAcceptance(name)
    for name in ChatReadingAcceptance.__dict__
    if name.startswith("test_")
  )
  result = unittest.TextTestRunner(verbosity=2).run(suite)
  raise SystemExit(0 if result.wasSuccessful() else 1)
