"""Ticket 21: resize real decorated Tauri windows, retaining public facts."""

import ctypes
import json

import win32con
import win32gui
from chat_reading_acceptance import ChatReadingAcceptance
from conversation_presentation_acceptance import ConversationPresentationAcceptance
from pagination_acceptance import PaginationAcceptance
from window_acceptance import REPO, wait_until


class ResponsiveNavigationAcceptance(ChatReadingAcceptance):
  artifact_root = REPO / ".scratch/frontend-completion/ticket-21/native"
  connect = PaginationAcceptance.connect
  seed_threads = PaginationAcceptance.seed_threads
  instrument_presentation = ConversationPresentationAcceptance.instrument_presentation
  close_overlay = ConversationPresentationAcceptance.close_overlay

  def start_empty(self):
    # Seeded list cases already have an automatically selected conversation.
    # Wait for the real list rather than assuming an empty application database.
    host = self.launch()
    self.connect()
    backend_snapshot = self.state("ready")
    wait_until(
      lambda: self.evaluate(
        "Boolean(document.querySelector('.session-list'))&&"
        "document.querySelector('.session-list').getAttribute('aria-busy')!=='true'"
      )
    )
    self.click("新建")
    wait_until(lambda: "从一个想法开始" in self.body())
    self.instrument_sends()
    thread_id = self.evaluate(
      "document.querySelector('.session[aria-current=true]').dataset.conversationId"
    )
    return host, backend_snapshot, thread_id

  def instrument_layout(self):
    self.instrument_presentation("""
      window.__preferenceWrites=[];
      const savePreference=Storage.prototype.setItem;
      Storage.prototype.setItem=function(key,value){
        if(key==='shikigen.desktop-navigation-collapsed.v1')
          window.__preferenceWrites.push(value);
        return savePreference.call(this,key,value);
      };
      """)
    wait_until(lambda: "从一个想法开始" in self.body())

  def resize_window(self, host, width, height):
    hwnd = self.window(host)
    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    for _ in range(5):
      viewport_metrics = self.evaluate(
        "({w:innerWidth,h:innerHeight,dpr:devicePixelRatio})"
      )
      if viewport_metrics["w"] == width and viewport_metrics["h"] == height:
        break
      left, top, right, bottom = win32gui.GetWindowRect(hwnd)
      win32gui.SetWindowPos(
        hwnd,
        0,
        0,
        0,
        right - left + round((width - viewport_metrics["w"]) * viewport_metrics["dpr"]),
        bottom
        - top
        + round((height - viewport_metrics["h"]) * viewport_metrics["dpr"]),
        win32con.SWP_NOMOVE | win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE,
      )
      wait_until(
        lambda viewport_metrics=viewport_metrics: (
          self.evaluate("innerWidth") != viewport_metrics["w"]
          or self.evaluate("innerHeight") != viewport_metrics["h"]
        )
      )
    wait_until(lambda: self.evaluate(f"innerWidth==={width}&&innerHeight==={height}"))
    breakpoint = (
      "wide-desktop"
      if width >= 1440
      else "compact-desktop"
      if width >= 1280
      else "tablet"
      if width >= 768
      else "phone"
    )
    wait_until(
      lambda: self.evaluate(
        "document.querySelector('.app')?.dataset.navigationBreakpoint==="
        + json.dumps(breakpoint)
      )
    )
    self.evaluate(
      "new Promise(resolve=>requestAnimationFrame("
      "()=>requestAnimationFrame(()=>resolve(true))))"
    )
    wait_until(
      lambda: self.evaluate(
        "document.querySelector('.workspace').getAnimations()"
        ".every(animation=>animation.playState!=='running')"
      )
    )
    metrics = self.measure_layout()
    metrics["native_window_rect"] = win32gui.GetWindowRect(hwnd)
    metrics["native_client_rect"] = win32gui.GetClientRect(hwnd)
    metrics["native_dpi"] = ctypes.windll.user32.GetDpiForWindow(hwnd)
    return metrics

  def measure_layout(self):
    return self.evaluate("""(() => {
      const measureElement=selector=>{
        const element=[...document.querySelectorAll(selector)]
          .find(element=>element.getClientRects().length);
        if(!element)return null;
        const elementRect=element.getBoundingClientRect();
        const computedStyle=getComputedStyle(element);
        return {x:elementRect.x,y:elementRect.y,
          width:elementRect.width,height:elementRect.height,
          right:elementRect.right,bottom:elementRect.bottom,
          font:computedStyle.fontFamily,fontSize:computedStyle.fontSize,lineHeight:computedStyle.lineHeight,
          background:computedStyle.backgroundColor,gap:computedStyle.gap,maxHeight:computedStyle.maxHeight,
          scrollHeight:element.scrollHeight,clientHeight:element.clientHeight,scrollTop:element.scrollTop};
      };
      return {width:innerWidth,height:innerHeight,dpr:devicePixelRatio,
        breakpoint:document.querySelector('.app').dataset.navigationBreakpoint,
        documentWidth:document.documentElement.scrollWidth,
        preference:localStorage.getItem('shikigen.desktop-navigation-collapsed.v1'),
        bar:measureElement('.app-bar'),workspace:measureElement('.workspace'),
        navigation:measureElement('.workspace > .navigation'),
        history:measureElement('.history'),
        chat:measureElement('.chat-workspace'),messages:measureElement('.message-container'),
        message:measureElement('.message'),avatar:measureElement('.message .avatar'),
        role:measureElement('.message-heading strong'),
        body:measureElement('.message-text'),
        composer:measureElement('.composer'),draft:measureElement('#message-draft'),
        actions:measureElement('.composer-toolbar .primary-button'),
        notices:measureElement('.workspace-notices'),drawer:measureElement('dialog.drawer'),
        sidebar:measureElement('dialog.sidebar-dialog'),dialogs:document.querySelectorAll('dialog[open]').length,
        focus:document.activeElement?.getAttribute('aria-label')??document.activeElement?.className};
    })()""")

  def click_selector(self, selector):
    self.assertTrue(
      self.evaluate(
        "(() => {const button=[...document.querySelectorAll("
        + json.dumps(selector)
        + ")].find(element=>element.getClientRects().length&&!element.disabled);"
        "if(!button)return false;button.focus();button.click();return true;})()"
      ),
      selector,
    )

  def open_menu(self):
    self.click_selector(".mobile-navigation, .history-toggle")
    wait_until(
      lambda: self.evaluate("document.querySelectorAll('dialog[open]').length") == 1
    )

  def capture_size(self, name, metrics=None):
    self.screenshot()
    (self.artifacts / f"{name}.png").write_bytes(
      (self.artifacts / "window.png").read_bytes()
    )
    (self.artifacts / f"{name}.json").write_text(
      json.dumps(metrics or self.measure_layout(), ensure_ascii=False, indent=2),
      encoding="utf-8",
    )

  def read_layout_requests(self):
    return self.evaluate(
      "window.__presentationRequests.filter(request=>"
      "request.path.endsWith('/messages')||request.path.endsWith('/stream')||request.method!=='GET')"
    )

  def press_key(self, key, code, vk, modifiers=0):
    self.call(
      "Input.dispatchKeyEvent",
      type="keyDown",
      key=key,
      code=code,
      windowsVirtualKeyCode=vk,
      modifiers=modifiers,
    )
    self.call(
      "Input.dispatchKeyEvent",
      type="keyUp",
      key=key,
      code=code,
      windowsVirtualKeyCode=vk,
      modifiers=modifiers,
    )

  def start_completed(self):
    (self.root / "allow-reading-stream").touch()
    host, backend_snapshot, thread = self.start_empty()
    self.instrument_layout()
    self.send("原稿布局与长正文验收")
    self.complete()
    wait_until(
      lambda: (
        not self.evaluate(
          "document.querySelector('.session-list')?.getAttribute('aria-busy')==='true'"
        )
      )
    )
    return host, backend_snapshot, thread

  def test_four_native_sizes_original_proportions_input_long_content_and_drawers(self):
    host, backend_snapshot, thread = self.start_completed()
    snapshots = []
    for width, height, nav_width in [
      (1440, 900, 256),
      (1280, 800, 64),
      (1024, 768, 64),
      (390, 844, None),
    ]:
      self.set_draft("")
      self.home()
      metrics = self.resize_window(host, width, height)
      self.assertEqual(metrics["bar"]["height"], 40)
      self.assertEqual(metrics["documentWidth"], width)
      self.assertIsNone(metrics["preference"])
      if nav_width is None:
        self.assertIsNone(metrics["navigation"])
      else:
        self.assertEqual(metrics["navigation"]["width"], nav_width)
      if width >= 1280:
        self.assertEqual(metrics["history"]["width"], 256)
      else:
        self.assertIsNone(metrics["history"])
      self.assertAlmostEqual(metrics["draft"]["height"], 48, delta=1)
      self.assertLessEqual(metrics["messages"]["width"], 840)
      self.assertEqual(metrics["avatar"]["width"], 28)
      self.assertEqual(metrics["message"]["gap"], "12px")
      self.assertEqual(metrics["role"]["fontSize"], "15px")
      self.assertEqual(metrics["role"]["lineHeight"], "22px")
      self.assertEqual(metrics["body"]["fontSize"], "14px")
      self.assertEqual(metrics["body"]["lineHeight"], "24px")
      self.capture_size(f"{width}-workspace", metrics)
      self.set_draft("\n".join(f"  原文 {n}" for n in range(30)))
      wait_until(lambda: self.measure_layout()["draft"]["height"] == 180)
      long_input = self.measure_layout()
      self.assertGreater(long_input["draft"]["scrollHeight"], 180)
      self.assertLessEqual(long_input["actions"]["bottom"], height)
      self.assertGreater(long_input["actions"]["height"], 0)
      if width < 1280:
        self.assertGreaterEqual(long_input["actions"]["height"], 44)
      self.assertTrue(
        self.evaluate(
          "[...document.querySelectorAll('.content-block pre')].some(element=>"
          "getComputedStyle(element).maxHeight==='320px'&&element.scrollHeight>element.clientHeight)"
        )
      )
      self.click_selector(".content-actions button")
      wait_until(lambda: self.measure_layout()["drawer"])
      drawer = self.measure_layout()["drawer"]
      self.assertAlmostEqual(drawer["width"], 400 if width >= 768 else width, delta=1)
      if width < 768:
        self.assertAlmostEqual(drawer["height"], height * 0.8, delta=1)
      self.assertEqual(self.measure_layout()["dialogs"], 1)
      self.capture_size(f"{width}-full-content")
      self.close_overlay()
      snapshots.append({"normal": metrics, "long_input": long_input, "drawer": drawer})
    self.assertEqual(self.evaluate("window.__preferenceWrites"), [])
    self.resize_window(host, 1440, 900)
    self.click_selector(".navigation-heading button")
    wait_until(lambda: self.measure_layout()["navigation"]["width"] == 64)
    self.capture_size("1440-collapsed")
    self.set_draft("启用发送 hover")
    rect = self.evaluate(
      "(() => {const buttonRect=document.querySelector("
      "'.composer-toolbar .primary-button').getBoundingClientRect();"
      "return {x:buttonRect.x+buttonRect.width/2,"
      "y:buttonRect.y+buttonRect.height/2};})()"
    )
    self.call("Input.dispatchMouseEvent", type="mouseMoved", **rect)
    wait_until(
      lambda: (
        self.evaluate(
          "getComputedStyle(document.querySelector("
          "'.composer-toolbar .primary-button')).backgroundColor"
        )
        == "rgb(67, 56, 202)"
      )
    )
    self.set_draft("宽度换行 " * 20)
    wide_draft_height = self.measure_layout()["draft"]["height"]
    self.resize_window(host, 390, 844)
    wait_until(lambda: self.measure_layout()["draft"]["height"] > wide_draft_height)
    narrow_draft_height = self.measure_layout()["draft"]["height"]
    self.resize_window(host, 1440, 900)
    wait_until(lambda: self.measure_layout()["draft"]["height"] == wide_draft_height)
    self.assertEqual(self.draft(), "宽度换行 " * 20)
    self.record(
      backend_snapshot=backend_snapshot,
      thread=thread,
      sizes=snapshots,
      hover="rgb(67, 56, 202)",
      draft_wrap_heights=[wide_draft_height, narrow_draft_height],
    )

  def test_only_desktop_choice_persists_through_native_restart_and_narrow_menus(self):
    host, backend_snapshot, thread = self.start_completed()
    self.resize_window(host, 1280, 800)
    self.click_selector(".workspace > .navigation .navigation-heading button")
    wait_until(lambda: self.measure_layout()["navigation"]["width"] == 256)
    self.assertEqual(self.evaluate("window.__preferenceWrites"), ["false"])
    self.set_draft("  桌面偏好\n  重启保留  ")
    for width, height in [(1024, 768), (390, 844)]:
      self.resize_window(host, width, height)
      self.open_menu()
      self.click_selector("dialog .sidebar-switch button[aria-pressed=false]")
      self.assertEqual(self.measure_layout()["dialogs"], 1)
      self.assertTrue(
        self.evaluate(
          "Boolean(document.querySelector("
          "'dialog .sidebar-view:not([hidden]) .navigation'))"
        )
      )
      self.assertEqual(self.evaluate("window.__preferenceWrites"), ["false"])
      self.close_overlay()
      self.assertTrue(
        self.evaluate(
          "document.activeElement.matches('.mobile-navigation,.history-toggle')"
        )
      )
    self.resize_window(host, 1440, 900)
    self.assertEqual(self.measure_layout()["navigation"]["width"], 256)
    self.quit(host)
    self.assertEqual(host.wait(timeout=15), 0)
    self.ws.close()
    self.ws = None
    restart_host = self.launch()
    self.connect()
    restart_snapshot = self.state("ready")
    wait_until(lambda: self.draft() == "  桌面偏好\n  重启保留  ")
    self.resize_window(restart_host, 1280, 800)
    self.assertEqual(self.measure_layout()["navigation"]["width"], 256)
    self.assertEqual(self.measure_layout()["preference"], "false")
    self.capture_size("native-restart")
    self.record(
      backend_snapshot=backend_snapshot,
      restart_snapshot=restart_snapshot,
      thread=thread,
      draft=self.draft(),
    )

  def test_menu_preserves_filter_pages_scroll_reading_and_single_foreground_focus(self):
    self.seed_threads(41)
    host, backend_snapshot, thread = self.start_completed()
    reading_position = self.pause_at("article.message.assistant:last-of-type")
    self.set_draft("  菜单切换\n  保留原文  ")
    self.evaluate("document.querySelector('.session-list').scrollTop=100000;void 0")
    wait_until(
      lambda: self.evaluate("document.querySelectorAll('.session').length") >= 40
    )
    self.evaluate(
      "(() => {const element=document.querySelector('.search input');"
      "Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')"
      ".set.call(element,'新会话');"
      "element.dispatchEvent(new Event('input',{bubbles:true}));})()"
    )
    self.evaluate("document.querySelector('.session-list').scrollTop=240;void 0")
    wait_until(
      lambda: self.evaluate("document.querySelector('.session-list').scrollTop") == 240
    )
    count = self.evaluate("document.querySelectorAll('.session').length")
    baseline = self.read_layout_requests()
    self.resize_window(host, 390, 844)
    self.open_menu()
    wait_until(
      lambda: (
        self.evaluate("document.querySelector('dialog .session-list').scrollTop") == 240
      )
    )
    self.assertEqual(
      self.evaluate("document.querySelector('dialog .search input').value"), "新会话"
    )
    self.assertEqual(
      self.evaluate("document.querySelectorAll('dialog .session').length"), count
    )
    self.click_selector("dialog .sidebar-switch button[aria-pressed=false]")
    self.assertTrue(
      self.evaluate("Boolean(document.querySelector('dialog .navigation-brand'))")
    )
    disabled_destinations = self.evaluate(
      "[...document.querySelectorAll('dialog .navigation nav button')]"
      ".filter(element=>element.disabled).map(element=>({title:element.title,"
      "label:element.getAttribute('aria-label')}))"
    )
    self.assertEqual(len(disabled_destinations), 4)
    self.assertTrue(
      all("暂未支持" in destination["label"] for destination in disabled_destinations)
    )
    self.click_selector("dialog .sidebar-switch button[aria-pressed=false]")
    wait_until(
      lambda: (
        self.evaluate("document.querySelector('dialog .session-list').scrollTop") == 240
      )
    )
    self.press_key("Tab", "Tab", 9, modifiers=8)
    self.assertTrue(
      self.evaluate("Boolean(document.activeElement.closest('dialog[open]'))")
    )
    self.close_overlay()
    self.open_menu()
    self.assertTrue(
      self.evaluate(
        "Boolean(document.querySelector('dialog .sidebar-view:not([hidden]) .history'))"
      )
    )
    self.click_selector("dialog .sidebar-switch button[aria-pressed=false]")
    self.click_selector("dialog .navigation-footer button[aria-label=快捷命令面板]")
    self.assertEqual(self.measure_layout()["dialogs"], 1)
    self.assertIn(
      "命令面板", self.evaluate("document.querySelector('dialog[open]').innerText")
    )
    self.close_overlay()
    self.open_menu()
    self.resize_window(host, 1280, 800)
    wait_until(lambda: self.measure_layout()["dialogs"] == 0)
    self.assertTrue(
      self.evaluate("document.activeElement.matches('.navigation-heading button')")
    )
    wait_until(
      lambda: self.evaluate("document.querySelector('.session-list').scrollTop") == 240
    )
    self.assertEqual(
      self.evaluate("document.querySelector('.search input').value"), "新会话"
    )
    self.assertEqual(self.read_layout_requests(), baseline)
    self.assertEqual(self.draft(), "  菜单切换\n  保留原文  ")
    self.assert_anchor(reading_position)
    self.record(
      backend_snapshot=backend_snapshot,
      thread=thread,
      baseline=baseline,
      final=self.read_layout_requests(),
      reading_position=reading_position,
      final_reading=self.geometry(),
      pages=count,
      disabled_destinations=disabled_destinations,
    )
    self.capture_size("menu-restored")

  def test_active_stream_layout_does_not_reconnect_cancel_or_hide_required_controls(
    self,
  ):
    (self.root / "missing-tray-icon").touch()
    host, backend_snapshot, thread = self.start_empty()
    self.instrument_layout()
    self.send("保持运行时切换布局")
    wait_until(lambda: "生成中" in self.body())
    wait_until(lambda: self.evaluate("Boolean(document.querySelector('.tray-notice'))"))
    self.home()
    reading_position = self.geometry()
    self.set_draft("运行中草稿")
    baseline = self.read_layout_requests()
    for width, height in [(1024, 768), (390, 844), (1440, 900)]:
      self.resize_window(host, width, height)
      if width < 1280:
        self.open_menu()
        metrics = self.measure_layout()
        self.assertGreater(metrics["workspace"]["y"], 40)
        self.assertAlmostEqual(
          metrics["sidebar"]["y"], metrics["workspace"]["y"], delta=1
        )
        self.click_selector("dialog .sidebar-switch button[aria-pressed=false]")
        if width == 1024:
          short_window_metrics = self.resize_window(host, 1024, 600)
          nav_geometry = self.evaluate("""(() => {
            const element=document.querySelector('dialog .navigation');
            const navigationList=element.querySelector('nav');
            const navigationHeader=element.querySelector('.navigation-heading');
            const navigationFooter=element.querySelector('.navigation-footer');
            navigationList.scrollTop=navigationList.scrollHeight;
            return {headerY:navigationHeader.getBoundingClientRect().top,
              footerBottom:navigationFooter.getBoundingClientRect().bottom,
              clientHeight:navigationList.clientHeight,scrollHeight:navigationList.scrollHeight,
              scrollTop:navigationList.scrollTop,overflow:getComputedStyle(navigationList).overflowY,
              commandsVisible:navigationFooter.querySelector('button').getClientRects().length>0};
          })()""")
          self.assertEqual(nav_geometry["overflow"], "auto")
          self.assertGreater(nav_geometry["scrollHeight"], nav_geometry["clientHeight"])
          self.assertGreater(nav_geometry["scrollTop"], 0)
          self.assertGreaterEqual(nav_geometry["headerY"], metrics["workspace"]["y"])
          self.assertLessEqual(nav_geometry["footerBottom"], 600)
          self.assertTrue(nav_geometry["commandsVisible"])
          self.capture_size(
            "tablet-short-navigation",
            {
              "layout": short_window_metrics,
              "navigation_scroll": nav_geometry,
            },
          )
          self.resize_window(host, 1024, 768)
        self.close_overlay()
      if width == 1024:
        self.click_selector(".content-actions button")
        metrics = self.measure_layout()
        self.assertAlmostEqual(
          metrics["drawer"]["y"], metrics["workspace"]["y"], delta=1
        )
        self.close_overlay()
      self.assertEqual(self.read_layout_requests(), baseline)
      self.assertEqual(self.draft(), "运行中草稿")
      self.assertEqual(
        self.evaluate(
          "document.querySelector('.composer-toolbar .primary-button').textContent"
        ),
        "取消运行",
      )
      self.assertLessEqual(self.measure_layout()["actions"]["bottom"], height)
      self.assert_anchor(reading_position)
    self.resize_window(host, 390, 844)
    self.click_selector(".composer-toolbar .primary-button")
    self.assertEqual(self.measure_layout()["dialogs"], 1)
    self.assertTrue(self.evaluate("document.activeElement.id==='continue-running'"))
    self.close_overlay()
    self.assertEqual(self.read_layout_requests(), baseline)
    self.assertFalse(any(request["path"].endswith("/cancel") for request in baseline))
    self.assertEqual(self.evaluate("window.__preferenceWrites"), [])
    (self.root / "allow-reading-stream").touch()
    wait_until(lambda: "阅读完成" in self.body())
    self.set_draft("\n".join("  长草稿原文" for _ in range(30)))
    self.evaluate("window.__failHistory=true")
    self.click("刷新数据")
    wait_until(
      lambda: self.evaluate(
        "document.querySelector('.workspace-notices').innerText.includes('读取')"
      )
    )
    metrics = self.measure_layout()
    self.assertLessEqual(metrics["notices"]["height"], min(844 * 0.25, 180))
    self.assertLessEqual(metrics["actions"]["bottom"], 844)
    self.assertEqual(metrics["documentWidth"], 390)
    self.capture_size("active-and-read-failure", metrics)
    self.record(
      backend_snapshot=backend_snapshot,
      thread=thread,
      baseline=baseline,
      final=self.read_layout_requests(),
      reading_position=reading_position,
      metrics=metrics,
      body=self.body(),
    )
