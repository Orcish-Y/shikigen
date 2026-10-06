"""Ticket 22: native Tauri command search, public actions and keyboard guards."""

import json
import sqlite3
import time

from responsive_navigation_acceptance import ResponsiveNavigationAcceptance
from window_acceptance import REPO, wait_until


class CommandPanelAcceptance(ResponsiveNavigationAcceptance):
  artifact_root = REPO / ".scratch/frontend-completion/ticket-22/native"

  def instrument_commands(self):
    self.instrument_presentation("""
      window.__preferenceWrites=[];
      const savePreference=Storage.prototype.setItem;
      Storage.prototype.setItem=function(key,value){
        if(key==='shikigen.desktop-navigation-collapsed.v1')window.__preferenceWrites.push(value);
        return savePreference.call(this,key,value);
      };
      const fetchFromPage=window.fetch.bind(window);
      window.__commandRequests=[];
      window.fetch=async(input,init)=>{
        const requestUrl=new URL(typeof input==='string'?input:input.url,location.href);
        if(requestUrl.pathname.startsWith('/api/'))window.__commandRequests.push({
          path:requestUrl.pathname,search:requestUrl.search,method:init?.method??'GET'});
        const response=await fetchFromPage(input,init);
        if(requestUrl.pathname==='/api/threads'&&init?.method==='POST'&&window.__holdCreate){
          window.__holdCreate=false;
          window.__createdThreadId=(await response.clone().json()).thread_id;
          await new Promise(resolve=>window.__releaseCreate=resolve);
        }
        return response;
      };
      window.__keyboardEvents=[];
      document.addEventListener('keydown',event=>{
        const keyRecord={key:event.key,repeat:event.repeat,
          isComposing:event.isComposing,
          keyCode:event.keyCode,ctrlKey:event.ctrlKey,metaKey:event.metaKey,
          target:event.target.id||event.target.getAttribute('aria-label')};
        window.__keyboardEvents.push(keyRecord);
        setTimeout(()=>keyRecord.defaultPrevented=event.defaultPrevented,0);
      },true);
    """)
    wait_until(
      lambda: self.evaluate(
        "Boolean(document.querySelector('.session-list'))&&"
        "document.querySelector('.session-list').getAttribute('aria-busy')!=='true'"
      )
    )
    wait_until(
      lambda: self.evaluate("!document.querySelector('#message-draft').disabled")
    )
    wait_until(
      lambda: (
        self.evaluate("document.querySelector('.toolbar-badge').textContent")
        in ["未开始", "运行中", "等待审批", "已完成", "已取消", "运行失败"]
      )
    )

  def seed_titles(self, count):
    thread_ids, timestamp = self.seed_threads(count)
    titles = {
      thread_id: f"已加载标题 {index:02d} · 中文会话"
      for index, thread_id in enumerate(sorted(thread_ids, reverse=True), 1)
    }
    with sqlite3.connect(self.root / "chat.db") as database:
      database.executemany(
        "UPDATE threads SET title=? WHERE id=?",
        [(title, thread_id) for thread_id, title in titles.items()],
      )
      database.commit()
    return titles, timestamp

  def set_input(self, selector, text):
    self.assertTrue(
      self.evaluate(
        "(() => {const input=document.querySelector("
        + json.dumps(selector)
        + ");if(!input)return false;input.focus();"
        "Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,"
        + json.dumps(text)
        + ");input.dispatchEvent(new Event('input',{bubbles:true}));return true;})()"
      )
    )

  def settle_keyboard(self):
    self.evaluate(
      "new Promise(resolve=>requestAnimationFrame("
      "()=>requestAnimationFrame(()=>resolve(true))))"
    )

  def press_shortcut(self, key, *, repeat=False, modifiers=2):
    self.call("Page.bringToFront")
    self.call(
      "Input.dispatchKeyEvent",
      type="keyDown",
      key=key,
      code="Key" + key.upper(),
      windowsVirtualKeyCode=ord(key.upper()),
      modifiers=modifiers,
      autoRepeat=repeat,
    )
    self.call(
      "Input.dispatchKeyEvent",
      type="keyUp",
      key=key,
      code="Key" + key.upper(),
      windowsVirtualKeyCode=ord(key.upper()),
      modifiers=modifiers,
    )
    self.settle_keyboard()

  def press_enter(self, *, repeat=False):
    self.call(
      "Input.dispatchKeyEvent",
      type="keyDown",
      key="Enter",
      code="Enter",
      windowsVirtualKeyCode=13,
      autoRepeat=repeat,
    )
    self.call(
      "Input.dispatchKeyEvent",
      type="keyUp",
      key="Enter",
      code="Enter",
      windowsVirtualKeyCode=13,
    )
    self.settle_keyboard()

  def read_dialog_title(self):
    return self.evaluate("document.querySelector('dialog[open] h2')?.textContent")

  def assert_single_dialog(self, title):
    wait_until(lambda: self.read_dialog_title() == title)
    self.assertEqual(
      self.evaluate("document.querySelectorAll('dialog[open]').length"), 1
    )

  def open_commands(self):
    self.press_shortcut("k")
    self.assert_single_dialog("命令面板")
    self.assertEqual(self.evaluate("document.activeElement.id"), "command-search")

  def select_from_commands(self, thread_id):
    self.open_commands()
    self.click_selector(f'[data-command-id="conversation:{thread_id}"]')
    wait_until(lambda: not self.read_dialog_title())
    wait_until(
      lambda: (
        self.evaluate(
          "document.querySelector('.session[aria-current=true]')?.dataset.conversationId"
        )
        == thread_id
      )
    )

  def count_workspace_posts(self):
    return self.evaluate(
      "window.__presentationRequests.filter(request=>request.method==='POST').length"
    )

  def capture_commands(self, name, **evidence):
    self.capture_size(
      name,
      self.evaluate("""(() => {
      const dialog=document.querySelector('dialog[open]');
      const results=document.querySelector('.command-results');
      const dialogRect=dialog?.getBoundingClientRect();
      const dialogStyle=dialog&&getComputedStyle(dialog);
      return {width:innerWidth,height:innerHeight,
        dialogs:document.querySelectorAll('dialog[open]').length,
        dialog:dialogRect&&{width:dialogRect.width,top:dialogRect.top,bottom:dialogRect.bottom,
          cssWidth:dialogStyle.width,maxWidth:dialogStyle.maxWidth,boxSizing:dialogStyle.boxSizing},
        results:results&&{clientHeight:results.clientHeight,scrollHeight:results.scrollHeight,scrollTop:results.scrollTop},
        focus:document.activeElement?.outerHTML,body:document.body.innerText,
        requests:window.__presentationRequests,request_details:window.__commandRequests,
        keys:window.__keyboardEvents};
    })()"""),
    )
    self.record(
      requests=self.evaluate("window.__presentationRequests"),
      request_details=self.evaluate("window.__commandRequests"),
      keyboard_events=self.evaluate("window.__keyboardEvents"),
      preference_writes=self.evaluate("window.__preferenceWrites"),
      **evidence,
    )

  def test_local_search_disabled_no_match_arrows_scroll_and_independent_sidebar(self):
    titles, timestamp = self.seed_titles(41)
    host, backend_snapshot, thread_id = self.start_empty()
    self.instrument_commands()
    self.resize_window(host, 1440, 900)
    self.evaluate("document.querySelector('.session-list').scrollTop=100000;void 0")
    wait_until(
      lambda: self.evaluate("document.querySelectorAll('.session').length") >= 40
    )
    self.set_input(".search input", "已加载标题")
    self.evaluate("document.querySelector('.session-list').scrollTop=180;void 0")
    self.set_draft("  命令搜索保留原文\n  缩进与尾空格  ")
    self.evaluate("document.querySelector('#message-draft').focus()")
    loaded_ids = self.evaluate(
      "[...document.querySelectorAll('.session')].map(row=>row.dataset.conversationId)"
    )
    missing_id = next(thread_id for thread_id in titles if thread_id not in loaded_ids)
    baseline = self.read_layout_requests()
    self.open_commands()
    self.assertEqual(
      self.evaluate("document.querySelector('dialog').getBoundingClientRect().width"),
      480,
    )
    self.assertTrue(
      self.evaluate(
        "document.querySelector('.command-results').scrollHeight>"
        "document.querySelector('.command-results').clientHeight"
      )
    )
    self.capture_commands(
      "long-loaded-list", timestamp=timestamp, loaded_ids=loaded_ids
    )
    for query in ["没有任何匹配xyz", titles[missing_id], "已完成"]:
      self.set_input("#command-search", query)
      wait_until(lambda: "没有匹配的操作或已加载会话" in self.body())
      self.press_enter()
      self.assert_single_dialog("命令面板")
      self.assertEqual(self.read_layout_requests(), baseline)
    self.set_input("#command-search", "运行详情")
    self.assertTrue(
      self.evaluate("document.querySelector('[data-command-id=run-details]').disabled")
    )
    self.assertIn(
      "尚未开始运行",
      self.evaluate(
        "document.querySelector('[data-command-id=run-details]').innerText"
      ),
    )
    self.press_enter()
    self.assert_single_dialog("命令面板")
    self.set_input("#command-search", "")
    self.press_key("ArrowUp", "ArrowUp", 38)
    wait_until(
      lambda: self.evaluate("document.querySelector('.command-results').scrollTop") > 0
    )
    self.assertTrue(
      self.evaluate(
        "document.querySelector('[aria-selected=true]').dataset.commandId.startsWith('conversation:')"
      )
    )
    self.press_key("ArrowDown", "ArrowDown", 40)
    self.assertEqual(
      self.evaluate("document.querySelector('[aria-selected=true]').dataset.commandId"),
      "create-conversation",
    )
    self.press_key("ArrowDown", "ArrowDown", 40)
    self.press_key("ArrowDown", "ArrowDown", 40)
    self.press_key("ArrowDown", "ArrowDown", 40)
    self.assertTrue(
      self.evaluate(
        "document.querySelector('[aria-selected=true]').dataset.commandId.startsWith('conversation:')"
      )
    )
    self.press_key("Escape", "Escape", 27)
    wait_until(lambda: not self.read_dialog_title())
    self.assertEqual(self.evaluate("document.activeElement.id"), "message-draft")
    self.assertEqual(
      self.evaluate("document.querySelector('.search input').value"), "已加载标题"
    )
    self.assertEqual(
      self.evaluate("document.querySelector('.session-list').scrollTop"), 180
    )
    self.assertEqual(self.read_layout_requests(), baseline)
    self.assertEqual(self.draft(), "  命令搜索保留原文\n  缩进与尾空格  ")
    self.assertTrue(
      self.evaluate(
        "window.__commandRequests.filter(request=>request.method==='GET'&&request.path==='/api/threads')"
        ".every(request=>[...new URLSearchParams(request.search).keys()]"
        ".every(key=>['limit','cursor'].includes(key)))"
      )
    )
    self.capture_commands(
      "closed-restored",
      backend_snapshot=backend_snapshot,
      thread_id=thread_id,
      missing_title=titles[missing_id],
      baseline=baseline,
    )

  def test_create_pending_shared_guards_and_late_create_preserves_new_selection(self):
    titles, _ = self.seed_titles(2)
    host, backend_snapshot, source_thread = self.start_empty()
    self.instrument_commands()
    self.set_draft("创建期间保留原会话草稿")
    self.evaluate("window.__holdCreate=true")
    self.set_input(".search input", "会话")
    self.press_shortcut("n")
    wait_until(lambda: self.evaluate("Boolean(window.__releaseCreate)"))
    for _ in range(3):
      self.press_shortcut("n", repeat=True)
    self.assertEqual(self.count_workspace_posts(), 1)
    self.assertEqual(
      self.evaluate("document.querySelector('.search input').value"), "会话"
    )
    self.open_commands()
    self.set_input("#command-search", "新建")
    self.assertTrue(
      self.evaluate(
        "document.querySelector('[data-command-id=create-conversation]').disabled"
      )
    )
    self.assertIn("正在创建会话", self.body())
    self.press_enter()
    self.press_shortcut("n")
    self.assert_single_dialog("命令面板")
    self.assertEqual(self.count_workspace_posts(), 1)
    self.capture_commands("create-pending", backend_snapshot=backend_snapshot)
    target_thread = next(iter(titles))
    self.set_input("#command-search", titles[target_thread])
    self.press_enter()
    wait_until(lambda: not self.read_dialog_title())
    wait_until(lambda: "从一个想法开始" in self.body())
    self.set_draft("切换后的新草稿")
    self.evaluate("window.__releaseCreate();window.__releaseCreate=null")
    wait_until(lambda: "会话已创建" in self.body())
    self.assertEqual(
      self.evaluate(
        "document.querySelector('.session[aria-current=true]').dataset.conversationId"
      ),
      target_thread,
    )
    self.assertEqual(self.draft(), "切换后的新草稿")
    self.assertEqual(self.count_workspace_posts(), 1)
    self.select_from_commands(source_thread)
    wait_until(lambda: self.draft() == "创建期间保留原会话草稿")
    self.capture_commands(
      "late-create-preserved",
      source_thread=source_thread,
      target_thread=target_thread,
      created_thread=self.evaluate("window.__createdThreadId"),
    )

  def test_late_history_running_switch_and_details_replace_without_second_stream(self):
    host, backend_snapshot, source_thread = self.start_empty()
    self.send("仍在运行的源会话")
    wait_until(lambda: "生成中" in self.body())
    self.set_draft("源会话运行中草稿")
    self.click("新建")
    wait_until(lambda: "从一个想法开始" in self.body())
    target_thread = self.evaluate(
      "document.querySelector('.session[aria-current=true]').dataset.conversationId"
    )
    self.set_draft("目标会话草稿")
    self.instrument_commands()
    wait_until(lambda: self.draft() == "目标会话草稿")
    self.evaluate("window.__holdThreadId=" + json.dumps(source_thread))
    self.select_from_commands(source_thread)
    wait_until(lambda: self.evaluate("Boolean(window.__releaseHistory)"))
    self.select_from_commands(target_thread)
    wait_until(lambda: self.draft() == "目标会话草稿")
    self.set_draft("目标会话迟到保护\n  原文")
    self.evaluate("window.__releaseHistory();window.__releaseHistory=null")
    self.settle_keyboard()
    self.assertEqual(self.draft(), "目标会话迟到保护\n  原文")
    self.assertEqual(
      self.evaluate(
        "document.querySelector('.session[aria-current=true]').dataset.conversationId"
      ),
      target_thread,
    )
    self.select_from_commands(source_thread)
    wait_until(
      lambda: (
        self.evaluate("document.querySelector('.toolbar-badge').textContent")
        == "运行中"
      )
    )
    wait_until(lambda: self.draft() == "源会话运行中草稿")
    wait_until(lambda: "观察已建立" in self.body())
    self.home()
    reading_position = self.geometry()
    baseline = self.read_layout_requests()
    self.open_commands()
    self.set_input("#command-search", "运行详情")
    self.assertFalse(
      self.evaluate("document.querySelector('[data-command-id=run-details]').disabled")
    )
    self.press_enter()
    self.assert_single_dialog("运行详情")
    for key in ["k", "n", "b"]:
      self.press_shortcut(key)
      self.assert_single_dialog("运行详情")
    self.assertEqual(self.read_layout_requests(), baseline)
    self.capture_commands("details-replacement", backend_snapshot=backend_snapshot)
    self.press_key("Escape", "Escape", 27)
    wait_until(lambda: not self.read_dialog_title())
    self.assertTrue(self.evaluate("document.activeElement.getClientRects().length>0"))
    self.assert_anchor(reading_position)
    self.assertEqual(self.draft(), "源会话运行中草稿")
    self.assertEqual(self.count_workspace_posts(), 0)
    (self.root / "allow-reading-stream").touch()
    wait_until(
      lambda: (
        self.evaluate("document.querySelector('.toolbar-badge').textContent")
        == "已完成"
      )
    )
    self.capture_commands(
      "late-history-preserved",
      source_thread=source_thread,
      target_thread=target_thread,
      reading_position=reading_position,
      baseline=baseline,
    )

  def test_four_sizes_shortcut_modal_permissions_tab_focus_and_navigation_preference(
    self,
  ):
    # The inherited start_completed installs a separate layout recorder. Avoid
    # layering two document scripts that count each storage/fetch call twice.
    (self.root / "allow-reading-stream").touch()
    host, backend_snapshot, thread_id = self.start_empty()
    self.instrument_commands()
    self.send("四档命令与导航验收")
    self.complete()
    wait_until(
      lambda: self.evaluate(
        "document.querySelector('.session-list').getAttribute('aria-busy')!=='true'"
      )
    )
    self.set_draft("  四档快捷键原文\n  保留  ")
    baseline = self.read_layout_requests()
    evidence = []
    for width, height in [(1440, 900), (1280, 800), (1024, 768), (390, 844)]:
      metrics = self.resize_window(host, width, height)
      focus_selector = ".search input" if width == 1280 else "#message-draft"
      if width == 1280:
        self.set_input(focus_selector, "保留过滤文本")
      else:
        self.evaluate("document.querySelector('#message-draft').focus()")
      self.open_commands()
      self.capture_commands(f"{width}-initial-commands", layout=metrics)
      self.assertEqual(
        self.evaluate("document.querySelector('dialog').getBoundingClientRect().width"),
        min(480, width - 32),
      )
      self.assertLessEqual(
        self.evaluate(
          "document.querySelector('dialog').getBoundingClientRect().bottom"
        ),
        height,
      )
      for key in ["n", "b"]:
        self.press_shortcut(key)
        self.assert_single_dialog("命令面板")
      self.evaluate(
        "[...document.querySelectorAll('dialog button:not(:disabled)')].at(-1).focus()"
      )
      self.press_key("Tab", "Tab", 9)
      self.assertTrue(
        self.evaluate(
          "document.activeElement.matches('dialog button[aria-label=关闭]')"
        )
      )
      self.press_key("Tab", "Tab", 9, modifiers=8)
      self.assertTrue(self.evaluate("document.activeElement.closest('dialog')!==null"))
      self.press_shortcut("k", repeat=True)
      self.assert_single_dialog("命令面板")
      self.capture_commands(f"{width}-commands", layout=metrics)
      self.press_shortcut("k")
      wait_until(lambda: not self.read_dialog_title())
      self.assertTrue(
        self.evaluate(
          "document.activeElement.matches(" + json.dumps(focus_selector) + ")"
        )
      )
      self.press_shortcut("b")
      if width >= 1280:
        preference_writes = self.evaluate("window.__preferenceWrites")
        self.assertEqual(len(preference_writes), len(evidence) + 1)
        self.press_shortcut("b", repeat=True)
        self.assertEqual(self.evaluate("window.__preferenceWrites"), preference_writes)
      else:
        self.assert_single_dialog("菜单")
        self.assertTrue(
          self.evaluate(
            "[...document.querySelectorAll('.sidebar-switch button')].some("
            "button=>button.textContent==='主导航'&&"
            "button.getAttribute('aria-pressed')==='true')"
          )
        )
        preference_writes = self.evaluate("window.__preferenceWrites")
        for key in ["k", "n"]:
          self.press_shortcut(key)
          self.assert_single_dialog("菜单")
        self.press_shortcut("b", repeat=True)
        self.assert_single_dialog("菜单")
        self.press_shortcut("b")
        wait_until(lambda: not self.read_dialog_title())
        self.assertEqual(self.evaluate("window.__preferenceWrites"), preference_writes)
        self.open_menu()
        self.assertTrue(
          self.evaluate(
            "[...document.querySelectorAll('.sidebar-switch button')].some("
            "button=>button.textContent==='会话列表'&&"
            "button.getAttribute('aria-pressed')==='true')"
          )
        )
        self.press_shortcut("b")
        self.assert_single_dialog("菜单")
        self.press_key("Escape", "Escape", 27)
        wait_until(lambda: not self.read_dialog_title())
        self.assertTrue(
          self.evaluate("document.activeElement.getClientRects().length>0")
        )
      self.assertEqual(self.read_layout_requests(), baseline)
      self.assertEqual(self.draft(), "  四档快捷键原文\n  保留  ")
      evidence.append(
        {
          "width": width,
          "height": height,
          "layout": metrics,
          "preference_writes": preference_writes,
        }
      )
    self.assertEqual(len(self.evaluate("window.__preferenceWrites")), 2)
    self.capture_commands(
      "four-sizes-finished",
      backend_snapshot=backend_snapshot,
      thread_id=thread_id,
      sizes=evidence,
    )

  def test_chinese_composition_repeat_and_cancel_content_foreground_guards(self):
    host, backend_snapshot, thread_id = self.start_empty()
    self.send("中文组合与确认保护")
    wait_until(lambda: "生成中" in self.body())
    self.instrument_commands()
    wait_until(lambda: "生成中" in self.body())
    self.set_draft("运行中原文")
    self.evaluate("document.querySelector('#message-draft').focus()")
    wait_until(lambda: "观察已建立" in self.body())
    baseline = self.read_layout_requests()
    self.call(
      "Input.imeSetComposition", text="中文候选", selectionStart=4, selectionEnd=4
    )
    for key in ["k", "n", "b"]:
      self.evaluate(
        "document.activeElement.dispatchEvent(new KeyboardEvent('keydown',{key:"
        + json.dumps(key)
        + ",ctrlKey:true,isComposing:true,keyCode:229,bubbles:true,cancelable:true}))"
      )
    self.assertFalse(self.read_dialog_title())
    self.assertEqual(self.read_layout_requests(), baseline)
    self.call("Input.insertText", text="中文候选")
    time.sleep(0.08)
    committed_draft = self.draft()
    self.open_commands()
    self.set_input("#command-search", "新建")
    self.call(
      "Input.imeSetComposition", text="中文候选", selectionStart=4, selectionEnd=4
    )
    self.evaluate(
      "document.activeElement.dispatchEvent(new KeyboardEvent('keydown',"
      "{key:'Enter',isComposing:true,keyCode:229,bubbles:true,cancelable:true}))"
    )
    self.assert_single_dialog("命令面板")
    self.call("Input.insertText", text="中文候选")
    self.evaluate(
      "document.activeElement.dispatchEvent(new KeyboardEvent('keydown',"
      "{key:'Enter',bubbles:true,cancelable:true}))"
    )
    self.assert_single_dialog("命令面板")
    time.sleep(0.08)
    self.set_input("#command-search", "新建")
    self.press_enter(repeat=True)
    self.assert_single_dialog("命令面板")
    self.assertEqual(self.read_layout_requests(), baseline)
    self.press_shortcut("k")
    wait_until(lambda: not self.read_dialog_title())
    self.click_selector(".composer-toolbar button.primary-button")
    self.assert_single_dialog("取消本次运行？")
    self.assertEqual(self.evaluate("document.activeElement.id"), "continue-running")
    for key in ["k", "n", "b"]:
      self.press_shortcut(key)
      self.assert_single_dialog("取消本次运行？")
    self.press_key("Escape", "Escape", 27)
    wait_until(lambda: not self.read_dialog_title())
    self.assertEqual(self.read_layout_requests(), baseline)
    self.assertEqual(self.draft(), committed_draft)
    self.click_selector(".content-actions button")
    content_title = self.read_dialog_title()
    self.assertTrue(content_title)
    for key in ["k", "n", "b"]:
      self.press_shortcut(key)
      self.assert_single_dialog(content_title)
    self.press_key("Escape", "Escape", 27)
    wait_until(lambda: not self.read_dialog_title())
    self.assertEqual(self.read_layout_requests(), baseline)
    self.assertEqual(self.count_workspace_posts(), 0)
    self.assertEqual(self.draft(), committed_draft)
    self.capture_commands(
      "ime-and-confirmation",
      backend_snapshot=backend_snapshot,
      thread_id=thread_id,
      composition=(
        "Real WebView CDP imeSetComposition/insertText plus explicit "
        "229/isComposing events; physical keyboard/system candidate UI "
        "deferred to ticket 23"
      ),
      baseline=baseline,
    )
