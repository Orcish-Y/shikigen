"""Actual Windows IME/keyboard UI; OS injections are labelled explicitly."""

import csv
import ctypes
import io
import json
import subprocess
import time
from ctypes import wintypes

import win32api
import win32con
import win32gui
import win32process
from native_workflow_acceptance import NativeWorkflowAcceptance
from window_acceptance import REPO, wait_until


class NativePlatformAcceptance(NativeWorkflowAcceptance):
  def read_native_controls(self, window, label, is_recorded=True):
    ui_result = subprocess.run(
      [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",  # This child only; no machine/user policy is changed.
        "-File",
        str(REPO / ".scratch/frontend-completion/ticket-23/read-native-ui.ps1"),
        "-WindowHandle",
        str(window),
      ],
      capture_output=True,
      timeout=20,
      creationflags=subprocess.CREATE_NO_WINDOW,
    )
    self.assertEqual(ui_result.returncode, 0, ui_result.stderr.decode(errors="replace"))
    controls = json.loads(ui_result.stdout.decode("utf-8-sig"))
    if is_recorded:
      (self.artifacts / f"{label}-controls.json").write_text(
        json.dumps(controls, ensure_ascii=False, indent=2), encoding="utf-8"
      )
    return controls

  def read_text_input_process_ids(self):
    process_result = subprocess.run(
      ["tasklist.exe", "/FI", "IMAGENAME eq TextInputHost.exe", "/FO", "CSV", "/NH"],
      capture_output=True,
      timeout=10,
      creationflags=subprocess.CREATE_NO_WINDOW,
    )
    self.assertEqual(process_result.returncode, 0)
    return {
      int(process_row[1])
      for process_row in csv.reader(
        io.StringIO(process_result.stdout.decode(errors="replace"))
      )
      if process_row and process_row[0].lower() == "textinputhost.exe"
    }

  def read_window_cloak(self, window):
    dwm = ctypes.WinDLL("dwmapi")
    dwm.DwmGetWindowAttribute.argtypes = (
      wintypes.HWND,
      wintypes.DWORD,
      ctypes.c_void_p,
      wintypes.DWORD,
    )
    cloak_flags = wintypes.DWORD()
    self.assertEqual(
      dwm.DwmGetWindowAttribute(window, 14, ctypes.byref(cloak_flags), 4), 0
    )
    return cloak_flags.value

  def find_system_windows(self, expected_class=None, is_candidate=False):
    system_windows = []

    def collect_window(window, _context):
      class_name = win32gui.GetClassName(window)
      is_classic_candidate = (
        class_name.startswith("Microsoft.IME.") and "candidate" in class_name.lower()
      )
      is_modern_input_host = win32process.GetWindowThreadProcessId(window)[
        1
      ] in getattr(self, "text_input_process_ids", set())
      if (
        win32gui.IsWindowVisible(window)
        and (
          class_name == expected_class
          or is_candidate
          and (is_classic_candidate or is_modern_input_host)
        )
        and (not is_candidate or self.read_window_cloak(window) == 0)
      ):
        system_windows.append(window)

    win32gui.EnumWindows(collect_window, None)
    return system_windows

  def begin_system_ime_composition(self):
    host, startup_snapshot, thread_id = self.start_empty()
    window = self.focus_native_window(host)
    self.text_input_process_ids = self.read_text_input_process_ids()
    previous_candidate_windows = set(self.find_system_windows(is_candidate=True))
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetKeyboardLayoutList.argtypes = (
      ctypes.c_int,
      ctypes.POINTER(wintypes.HANDLE),
    )
    keyboard_layouts = (wintypes.HANDLE * 16)()
    layout_count = user32.GetKeyboardLayoutList(16, keyboard_layouts)
    chinese_layout = next(
      (
        layout for layout in keyboard_layouts[:layout_count] if layout & 0xFFFF == 0x804
      ),
      None,
    )
    self.assertIsNotNone(chinese_layout, "no loaded Chinese keyboard layout")
    win32gui.PostMessage(window, 0x50, 0, chinese_layout)  # WM_INPUTLANGCHANGEREQUEST
    self.evaluate("document.querySelector('#message-draft').focus()")
    self.evaluate("""(() => {
      window.__systemImeEvents=[];
      window.__scriptCompositionDispatches=[];
      const dispatchNativeEvent=EventTarget.prototype.dispatchEvent;
      EventTarget.prototype.dispatchEvent=function(event){
        if(event.type.startsWith('composition'))
          window.__scriptCompositionDispatches.push({type:event.type,data:event.data});
        return dispatchNativeEvent.call(this,event);
      };
      for(const type of [
        'compositionstart','compositionupdate','compositionend','keydown'])
        document.addEventListener(type,event=>window.__systemImeEvents.push({
          type,key:event.key,data:event.data,isComposing:event.isComposing,
          isTrusted:event.isTrusted}),true);
    })()""")
    composition_attempts = []
    for attempt in range(2):
      self.evaluate("window.__systemImeEvents=[]")
      for letter in "NIHAO":
        self.press_windows_keys(ord(letter))
      wait_until(
        lambda: self.evaluate(
          "document.querySelector('#message-draft')"
          ".value.replaceAll(\"'\",'').toLowerCase().endsWith('nihao')"
        )
      )
      composition_events = self.evaluate("window.__systemImeEvents")
      has_composition_start = any(
        event["type"] == "compositionstart" for event in composition_events
      )
      composition_updates = [
        event for event in composition_events if event["type"] == "compositionupdate"
      ]
      preedit_text = composition_updates[-1]["data"] if composition_updates else ""
      has_complete_preedit = (
        has_composition_start and preedit_text.replace("'", "").lower() == "nihao"
      )
      composition_attempts.append(
        {
          "attempt": attempt + 1,
          "events": composition_events,
          "draft": self.draft(),
          "has_complete_preedit": has_complete_preedit,
        }
      )
      (self.artifacts / "ime-start-attempts.json").write_text(
        json.dumps(composition_attempts, ensure_ascii=False, indent=2), encoding="utf-8"
      )
      if has_complete_preedit:
        break
      self.assertEqual(
        attempt, 0, "NIHAO is not wholly inside the current OS composition"
      )
      previous_end_count = sum(
        event["type"] == "compositionend" for event in composition_events
      )
      self.press_windows_keys(win32con.VK_ESCAPE)
      if has_composition_start:
        wait_until(
          lambda previous_end_count=previous_end_count: (
            self.evaluate(
              "window.__systemImeEvents.filter(event=>"
              "event.type==='compositionend').length"
            )
            > previous_end_count
          )
        )
      self.set_draft("")
      if not has_composition_start:
        self.press_windows_keys(win32con.VK_SHIFT)
    wait_until(
      lambda: self.evaluate(
        "document.querySelector('#message-draft').value.replaceAll(\"'\",'')"
        ".toLowerCase()==='nihao'"
      )
    )
    return host, startup_snapshot, thread_id, window, previous_candidate_windows

  def assert_ime_enter_keeps_unsent_pinyin(self, startup_snapshot, thread_id):
    # Microsoft Pinyin: Enter closes candidates without selecting one; Space
    # selects the focused Chinese candidate. Do not expect Enter to produce 你好.
    # https://support.microsoft.com/en-us/windows/hardware/input-devices/microsoft-simplified-chinese-ime
    previous_key_count = self.evaluate(
      "window.__systemImeEvents.filter(event=>event.type==='keydown').length"
    )
    self.press_windows_keys(win32con.VK_RETURN)
    wait_until(
      lambda: self.evaluate(
        "window.__systemImeEvents.some(event=>event.type==='compositionend')"
      )
    )
    composition_end = next(
      event
      for event in reversed(self.evaluate("window.__systemImeEvents"))
      if event["type"] == "compositionend"
    )
    ime_events = self.evaluate("window.__systemImeEvents")
    script_dispatches = self.evaluate("window.__scriptCompositionDispatches")
    (self.artifacts / "ime-completion-trace.json").write_text(
      json.dumps(
        {
          "events": ime_events,
          "script_dispatches": script_dispatches,
          "browser": self.call("Browser.getVersion"),
        },
        ensure_ascii=False,
        indent=2,
      ),
      encoding="utf-8",
    )
    # Browser-generated compositionend can have isTrusted=false. Keep that
    # value as evidence, verify native key input and no JavaScript dispatch.
    # Blink queues compositionend through DispatchScopedEvent, while start and
    # update use EventTarget::DispatchEvent, which explicitly marks trusted.
    key_events = [event for event in ime_events if event["type"] == "keydown"]
    self.assertGreater(len(key_events), previous_key_count)
    self.assertTrue(key_events[-1]["isTrusted"])
    self.assertIn(key_events[-1]["key"], ("Enter", "Process"))
    self.assertEqual(script_dispatches, [])
    wait_until(lambda: self.draft() == composition_end["data"])
    self.assertEqual(self.draft().replace("'", "").lower(), "nihao")
    self.evaluate(
      "new Promise(resolve=>requestAnimationFrame("
      "()=>requestAnimationFrame(()=>resolve(true))))"
    )
    self.assertEqual(
      self.client.get(
        startup_snapshot["base_url"] + f"/api/threads/{thread_id}/messages"
      ).json()["data"],
      [],
    )
    self.assertEqual(
      self.evaluate("document.querySelectorAll('dialog[open]').length"), 0
    )

  def test_real_system_ime_enter_ends_composition_without_creating_run(self):
    host, startup_snapshot, thread_id, window, _ = self.begin_system_ime_composition()
    before_enter_events = self.evaluate("window.__systemImeEvents")
    self.assertTrue(
      any(
        event["type"] == "compositionstart" and event["isTrusted"]
        for event in before_enter_events
      )
    )
    self.assertEqual(win32gui.GetForegroundWindow(), window)
    self.assert_ime_enter_keeps_unsent_pinyin(startup_snapshot, thread_id)
    self.record(
      startup_snapshot=startup_snapshot,
      thread_id=thread_id,
      before_enter_events=before_enter_events,
      ime_events=self.evaluate("window.__systemImeEvents"),
      draft=self.draft(),
      scope=(
        "actual installed OS IME composition/Enter through SendInput; "
        "candidate-window observation is a separate, still-required case"
      ),
    )
    self.capture_native_frame(host, "ime-enter")
    self.screenshot()
    self.quit(host)
    self.assertEqual(host.wait(timeout=15), 0)

  def test_real_system_ime_candidate_enter_commits_draft_without_sending(self):
    host, startup_snapshot, thread_id, window, previous_candidate_windows = (
      self.begin_system_ime_composition()
    )
    composition_events = self.evaluate("window.__systemImeEvents")
    candidate_windows = wait_until(
      lambda: [
        candidate_window
        for candidate_window in self.find_system_windows(is_candidate=True)
        if candidate_window not in previous_candidate_windows
      ],
      timeout=10,
    )
    for candidate_index, candidate_window in enumerate(candidate_windows):
      self.assertEqual(win32gui.GetForegroundWindow(), window)
      self.assertTrue(
        self.evaluate(
          "window.__systemImeEvents.at(-1)?.isComposing===true"
          "||window.__systemImeEvents.at(-1)?.type==='compositionupdate'"
        )
      )
      candidate_label = f"ime-candidate-{candidate_index}"
      candidate_controls = self.read_native_controls(
        candidate_window, candidate_label, is_recorded=False
      )
      self.assertTrue(
        any("你好" in control.get("name", "") for control in candidate_controls),
        "input host UIA does not expose this composition's expected candidate",
      )
      (self.artifacts / f"{candidate_label}-controls.json").write_text(
        json.dumps(candidate_controls, ensure_ascii=False, indent=2), encoding="utf-8"
      )
      self.capture_window_frame(
        candidate_window, candidate_label, is_desktop_capture=True
      )
    (self.artifacts / "ime-before-enter.json").write_text(
      json.dumps(
        {
          "events": composition_events,
          "candidate_windows": candidate_windows,
          "draft": self.draft(),
        },
        ensure_ascii=False,
        indent=2,
      ),
      encoding="utf-8",
    )
    self.assertTrue(
      any(
        event["type"] == "compositionstart" and event["isTrusted"]
        for event in composition_events
      ),
      "OS Chinese IME did not enter a native composition",
    )
    self.assertTrue(candidate_windows, "no actual candidate window observed")
    self.assert_ime_enter_keeps_unsent_pinyin(startup_snapshot, thread_id)
    self.record(
      startup_snapshot=startup_snapshot,
      thread_id=thread_id,
      candidate_windows=candidate_windows,
      candidate_association=(
        "newly visible during this nihao composition; "
        "target Tauri window still owns OS foreground before capture"
      ),
      draft=self.draft(),
      ime_events=self.evaluate("window.__systemImeEvents"),
      scope=(
        "actual installed OS IME and candidate window via SendInput; "
        "no CDP IME simulation"
      ),
    )
    self.screenshot()
    self.quit(host)
    self.assertEqual(host.wait(timeout=15), 0)

  def test_real_system_ime_space_selects_chinese_then_explicit_enter_sends_once(self):
    (self.root / "allow-reading-stream").touch()
    host, startup_snapshot, thread_id, window, _ = self.begin_system_ime_composition()
    self.assertEqual(win32gui.GetForegroundWindow(), window)
    self.press_windows_keys(win32con.VK_SPACE)
    wait_until(lambda: self.draft() == "你好")
    composition_events = self.evaluate("window.__systemImeEvents")
    self.assertTrue(
      any(event["type"] == "compositionend" for event in composition_events)
    )
    self.assertTrue(
      any(
        event["type"] == "compositionstart" and event["isTrusted"]
        for event in composition_events
      )
    )
    self.assertEqual(self.evaluate("window.__scriptCompositionDispatches"), [])
    self.assertEqual(
      self.client.get(
        startup_snapshot["base_url"] + f"/api/threads/{thread_id}/messages"
      ).json()["data"],
      [],
    )
    self.press_windows_keys(win32con.VK_RETURN)
    wait_until(
      lambda: (
        self.evaluate("document.querySelector('.toolbar-badge').textContent")
        == "已完成"
      ),
      timeout=30,
    )
    message_history = self.client.get(
      startup_snapshot["base_url"] + f"/api/threads/{thread_id}/messages"
    ).json()["data"]
    human_messages = [
      message for message in message_history if message["content"]["type"] == "human"
    ]
    self.assertEqual(len(human_messages), 1)
    self.assertEqual(human_messages[0]["content"]["content"], "你好")
    self.record(
      startup_snapshot=startup_snapshot,
      thread_id=thread_id,
      message_history=message_history,
      composition_events=composition_events,
      scope=(
        "actual OS IME Space selection and explicit Windows Enter; "
        "no candidate UI capture"
      ),
    )
    self.capture_native_frame(host, "ime-chinese-submit")
    self.screenshot()
    self.quit(host)
    self.assertEqual(host.wait(timeout=15), 0)

  def test_actual_windows_on_screen_keyboard_with_long_draft(self):
    host, startup_snapshot, thread_id = self.start_empty()
    self.resize_window(host, 390, 600)
    self.focus_native_window(host)
    self.set_draft("软键盘下的原文草稿\n" * 30)
    keyboard_windows = self.find_system_windows(expected_class="OSKMainClass")
    is_keyboard_preexisting = bool(keyboard_windows)
    if not keyboard_windows:
      self.press_windows_keys(win32con.VK_LWIN, win32con.VK_CONTROL, ord("O"))
      keyboard_windows = wait_until(
        lambda: self.find_system_windows(expected_class="OSKMainClass"), timeout=15
      )
    self.assertEqual(len(keyboard_windows), 1)
    keyboard_window = keyboard_windows[0]
    if not is_keyboard_preexisting:
      self.addCleanup(self.close_created_keyboard, keyboard_window)
    keyboard_controls = self.read_native_controls(keyboard_window, "soft-keyboard")
    keyboard_frame = self.capture_window_frame(
      keyboard_window, "soft-keyboard", is_desktop_capture=True
    )
    self.capture_native_frame(host, "soft-keyboard-app")
    self.record(
      startup_snapshot=startup_snapshot,
      thread_id=thread_id,
      keyboard_frame=keyboard_frame,
      keyboard_controls=keyboard_controls,
      keyboard_pid=win32process.GetWindowThreadProcessId(keyboard_window)[1],
      is_keyboard_preexisting=is_keyboard_preexisting,
      app_layout=self.measure_layout(),
      scope=(
        "actual Windows accessibility On-Screen Keyboard; "
        "not a TabTip or physical touch claim"
      ),
    )
    self.assertTrue(keyboard_controls)
    self.assertEqual(self.draft(), "软键盘下的原文草稿\n" * 30)
    self.assertTrue(
      self.evaluate(
        "(() => {const button=document.querySelector("
        "'.composer-toolbar .primary-button');"
        "return button?.disabled===false&&"
        "button.textContent.trim().startsWith('发送')})()"
      )
    )
    # Exercise the real keyboard key, rather than only proving the keyboard UI
    # is present. This fixed key position comes from the captured OSK layout.
    self.assertFalse(is_keyboard_preexisting, "do not type through a user's OSK")
    window = self.window(host)
    win32gui.PostMessage(window, 0x50, 0, 0x04090409)
    self.evaluate("""(() => {
      const draft=document.querySelector('#message-draft');
      draft.focus();draft.setSelectionRange(draft.value.length,draft.value.length);
      window.__oskKeyEvents=[];
      draft.addEventListener('keydown',event=>window.__oskKeyEvents.push({
        key:event.key,isTrusted:event.isTrusted,isComposing:event.isComposing}));
    })()""")
    keyboard_left, keyboard_top, keyboard_right, keyboard_bottom = (
      win32gui.GetWindowRect(keyboard_window)
    )
    key_position = (
      keyboard_left + round((keyboard_right - keyboard_left) * 0.147),
      keyboard_top + round((keyboard_bottom - keyboard_top) * 0.603),
    )
    original_cursor = win32api.GetCursorPos()
    try:
      win32api.SetCursorPos(key_position)
      self.assertEqual(
        win32gui.GetAncestor(win32gui.WindowFromPoint(key_position), 2), keyboard_window
      )
      win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
      win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
      wait_until(lambda: self.draft() == "软键盘下的原文草稿\n" * 30 + "a")
    finally:
      win32api.SetCursorPos(original_cursor)
    self.assertTrue(
      any(
        event["key"] == "a" and event["isTrusted"]
        for event in self.evaluate("window.__oskKeyEvents")
      )
    )
    button_position = self.evaluate("""(() => {
      const bounds=document.querySelector('.composer-toolbar .primary-button')
        .getBoundingClientRect();
      return {x:(bounds.x+bounds.width/2)*devicePixelRatio,
        y:(bounds.y+bounds.height/2)*devicePixelRatio};
    })()""")
    button_screen_position = win32gui.ClientToScreen(
      window, (round(button_position["x"]), round(button_position["y"]))
    )
    self.assertEqual(
      win32gui.GetAncestor(win32gui.WindowFromPoint(button_screen_position), 2),
      window,
      "OSK obscures the actual composer action",
    )
    self.assertEqual(
      self.client.get(
        startup_snapshot["base_url"] + f"/api/threads/{thread_id}/messages"
      ).json()["data"],
      [],
    )
    (self.artifacts / "soft-keyboard-input.json").write_text(
      json.dumps(
        {
          "key_position": key_position,
          "draft": self.draft(),
          "key_events": self.evaluate("window.__oskKeyEvents"),
          "button_screen_position": button_screen_position,
          "scope": "actual OSK key mouse input; no TabTip or physical finger",
        },
        ensure_ascii=False,
        indent=2,
      ),
      encoding="utf-8",
    )
    self.quit(host)
    self.assertEqual(host.wait(timeout=15), 0)

  def close_created_keyboard(self, keyboard_window):
    if win32gui.IsWindow(keyboard_window) and win32gui.IsWindowVisible(keyboard_window):
      # OSK's UIAccess protection rejects WM_CLOSE from this test process.
      # Use its actual Windows shortcut, only for the exact window we created.
      self.press_windows_keys(win32con.VK_LWIN, win32con.VK_CONTROL, ord("O"))
      wait_until(
        lambda: (
          not win32gui.IsWindow(keyboard_window)
          or not win32gui.IsWindowVisible(keyboard_window)
        ),
        timeout=15,
      )

  def arrange_narrow_window_in_work_area(self, host, width, height):
    # Query in this test's DPI-aware coordinate space. A separate shell's
    # virtualized monitor coordinates cannot be used with native mouse input.
    window = self.window(host)
    original_rect = win32gui.GetWindowRect(window)
    window_width = original_rect[2] - original_rect[0]
    window_height = original_rect[3] - original_rect[1]
    monitors = [
      win32api.GetMonitorInfo(monitor)
      for monitor, _device_context, _bounds in win32api.EnumDisplayMonitors()
    ]
    suitable_monitors = [
      monitor
      for monitor in monitors
      if monitor["Work"][2] - monitor["Work"][0] >= window_width
      and monitor["Work"][3] - monitor["Work"][1] >= window_height
    ]
    self.assertTrue(suitable_monitors, "no monitor work area fits the native window")
    work_area = suitable_monitors[0]["Work"]
    # Move only the owned window. Preserve the taskbar and any existing apps;
    # the bottom-right placement also leaves room alongside the auxiliary OSK.
    spare_width = work_area[2] - work_area[0] - window_width
    spare_height = work_area[3] - work_area[1] - window_height
    win32gui.SetWindowPos(
      window,
      0,
      work_area[2] - window_width - min(16, spare_width),
      work_area[3] - window_height - min(16, spare_height),
      0,
      0,
      win32con.SWP_NOSIZE | win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE,
    )
    # Moving across monitors may change DPI; recheck the exact approved CSS
    # dimensions, then require the final native frame to remain on screen.
    layout = self.resize_window(host, width, height)
    native_rect = win32gui.GetWindowRect(window)
    (self.artifacts / "work-area-placement.json").write_text(
      json.dumps(
        {
          "monitors": monitors,
          "work_area": work_area,
          "original_rect": original_rect,
          "native_rect": native_rect,
          "layout": layout,
        },
        ensure_ascii=False,
        indent=2,
      ),
      encoding="utf-8",
    )
    self.assertGreaterEqual(native_rect[0], work_area[0])
    self.assertGreaterEqual(native_rect[1], work_area[1])
    self.assertLessEqual(native_rect[2], work_area[2])
    self.assertLessEqual(native_rect[3], work_area[3])
    return layout

  def test_osk_long_draft_tray_notice_and_native_cancel_remain_reachable(self):
    # Exercise the actual native tray-error banner through the existing
    # acceptance host's missing-icon fixture before it creates the tray.
    (self.root / "missing-tray-icon").touch()
    self.fixture.env["DESKTOP_TEST_READING_APPROVAL"] = "1"
    host, startup_snapshot, thread_id = self.start_empty()
    self.instrument_coexistence_faults()
    self.instrument_layout()
    self.send("软键盘、长内容与托盘提示联合验收")
    wait_until(lambda: "生成中" in self.body())
    wait_until(lambda: self.evaluate("Boolean(document.querySelector('.tray-notice'))"))
    self.resize_window(host, 390, 600)
    self.arrange_narrow_window_in_work_area(host, 390, 600)
    window = self.focus_native_window(host)
    long_draft = "软键盘下的下一条消息草稿\n" * 30
    self.set_coexistence_draft(long_draft)
    self.home()
    reading_position = self.geometry()
    self.assertFalse(reading_position["following"])
    self.assertEqual(self.find_system_windows(expected_class="OSKMainClass"), [])
    # OSK overlays Windows windows; it does not resize the WebView viewport.
    self.press_windows_keys(win32con.VK_LWIN, win32con.VK_CONTROL, ord("O"))
    keyboard_windows = wait_until(
      lambda: self.find_system_windows(expected_class="OSKMainClass"), timeout=15
    )
    self.assertEqual(len(keyboard_windows), 1)
    keyboard_window = keyboard_windows[0]
    self.addCleanup(self.close_created_keyboard, keyboard_window)
    keyboard_pid = win32process.GetWindowThreadProcessId(keyboard_window)[1]
    self.assertEqual(self.draft(), long_draft)
    self.assert_anchor(reading_position)
    layout = self.measure_layout()
    self.assertEqual((layout["width"], layout["height"]), (390, 600))
    self.assertEqual(layout["documentWidth"], 390)
    self.assertLessEqual(layout["actions"]["bottom"], 600)
    self.assertTrue(self.evaluate("Boolean(document.querySelector('.tray-notice'))"))
    action_position = self.evaluate("""(() => {
      const button=document.querySelector('.composer-toolbar .primary-button');
      if(button.disabled||button.textContent.trim()!=='取消运行')return null;
      const bounds=button.getBoundingClientRect();
      return {x:(bounds.x+bounds.width/2)*devicePixelRatio,
        y:(bounds.y+bounds.height/2)*devicePixelRatio};
    })()""")
    self.assertIsNotNone(action_position)
    action_screen_position = win32gui.ClientToScreen(
      window, (round(action_position["x"]), round(action_position["y"]))
    )
    original_cursor = win32api.GetCursorPos()
    try:
      win32api.SetCursorPos(action_screen_position)
      self.assertEqual(
        win32gui.GetAncestor(win32gui.WindowFromPoint(action_screen_position), 2),
        window,
        "OSK obscures the actual cancellation control",
      )
      win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
      win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
      wait_until(
        lambda: self.evaluate(
          "Boolean(document.querySelector('dialog[open]'))&&"
          "document.querySelector('dialog[open]').innerText.includes('确认取消')"
        )
      )
      self.assertEqual(win32gui.GetForegroundWindow(), window)
      self.press_windows_keys(win32con.VK_ESCAPE)
      wait_until(
        lambda: self.evaluate("document.querySelectorAll('dialog[open]').length") == 0
      )
    finally:
      win32api.SetCursorPos(original_cursor)
    self.assertEqual(self.draft(), long_draft)
    self.assert_anchor(reading_position)
    self.assertEqual(
      self.evaluate("document.querySelector('.toolbar-badge').textContent"), "运行中"
    )
    workflow = self.finish_coexistence_workflow(
      host, startup_snapshot, thread_id, long_draft, "osk", keyboard_window
    )
    # IsWindowVisible and hit testing can succeed before OSK's first composed
    # frame. Capture after the actual workflow, once its UI has been present
    # throughout all four operations; do not mistake an early background frame
    # for the keyboard. Its HWND and screen-point guards still apply.
    self.read_native_controls(keyboard_window, "osk-coexistence")
    self.assertEqual(ctypes.windll.dwmapi.DwmFlush(), 0)
    keyboard_frame = self.capture_window_frame(
      keyboard_window, "osk-coexistence", is_desktop_capture=True
    )
    self.record(
      startup_snapshot=startup_snapshot,
      thread_id=thread_id,
      keyboard_window=keyboard_window,
      keyboard_pid=keyboard_pid,
      keyboard_frame=keyboard_frame,
      layout=layout,
      reading_position=reading_position,
      action_screen_position=action_screen_position,
      draft=long_draft,
      workflow=workflow,
      scope=(
        "actual OSK present alongside owned Tauri window, long draft/reading/"
        "native missing-icon TrayNotice, Win32 mouse cancellation dialog and "
        "Windows Esc, approval, exact send, GET reconnect and confirmed cancellation; "
        "no OSK key injection, TabTip or physical finger claim"
      ),
    )
    self.capture_native_frame(host, "osk-coexistence-app")
    self.screenshot()
    self.close_created_keyboard(keyboard_window)
    # With no tray, the real close policy exits instead of hiding the window.
    win32gui.PostMessage(window, win32con.WM_CLOSE, 0, 0)
    self.assertEqual(host.wait(timeout=15), 0)

  def instrument_coexistence_faults(self):
    # Only the public transport boundary is faulted. The actual owned backend
    # continues its run, with real metadata, deltas, history and cancellation.
    self.call(
      "Page.addScriptToEvaluateOnNewDocument",
      source="""(() => {
        window.__coexistenceRequests=[];
        window.__coexistenceApiRequests=[];
        window.__nativeControlEvents=[];
        for(const type of ['pointerdown','pointerup','click'])
          document.addEventListener(type,event=>window.__nativeControlEvents.push({
            type,isTrusted:event.isTrusted,x:event.clientX,y:event.clientY,
            target:event.target.closest('button,label')?.textContent.trim()
              ??event.target.tagName}),true);
        const readBackend=window.fetch.bind(window);
        window.fetch=async (url,init)=>{
          const path=new URL(String(url)).pathname;
          const method=init?.method??'GET';
          if(path.startsWith('/api/'))window.__coexistenceApiRequests.push({path,method});
          if(path.endsWith('/stream'))window.__coexistenceRequests.push({path,method});
          if(method==='GET'&&path.endsWith('/stream')&&window.__failCoexistenceGets>0){
            window.__failCoexistenceGets--;
            return Response.json({detail:'联合验收观察故障'},{status:503});
          }
          const response=await readBackend(url,init);
          if(method!=='POST'||!path.endsWith('/stream')||!window.__dropCoexistencePost)
            return response;
          window.__dropCoexistencePost=false;
          const reader=response.body.getReader();
          const decoder=new TextDecoder();
          const body=new ReadableStream({async start(controller){
            let frames='';
            try {
              while(true){
                const {value,done}=await reader.read();
                if(done)throw new Error('完整delta前流已结束');
                frames+=decoder.decode(value,{stream:true}).replaceAll('\\r\\n','\\n');
                controller.enqueue(value);
                if(/event: delta[\\s\\S]*?\\n\\n/.test(frames)){
                  controller.close();await reader.cancel();return;
                }
              }
            } catch(error){controller.error(error);}
          }});
          return new Response(body,{headers:response.headers});
        };
      })()""",
    )

  def set_coexistence_draft(self, draft_text):
    self.set_draft(draft_text)
    wait_until(lambda: self.draft() == draft_text)
    if draft_text.count("\n") >= 20:
      wait_until(
        lambda: self.evaluate(
          "document.querySelector('#message-draft').getBoundingClientRect().height===180"
        )
      )
    # React/ResizeObserver must finish resizing before Home captures intent.
    wait_until(
      lambda: self.evaluate("""(async () => {
      const timeline=document.querySelector('.timeline');
      const before={height:timeline.clientHeight,top:timeline.scrollTop};
      for(let frame=0;frame<3;frame++)
        await new Promise(resolve=>requestAnimationFrame(resolve));
      return timeline.clientHeight===before.height
        &&Math.abs(timeline.scrollTop-before.top)<=1;
    })()""")
    )

  def click_native_control(self, host, selector, label):
    self.focus_native_window(host)
    # Scroll through browser input, which preserves actual reading intent.
    # A programmatic scrollIntoView would be restored to the remembered anchor.
    find_target = (
      "const target=[...document.querySelectorAll("
      + json.dumps(selector)
      + ")].find(element=>element.getClientRects().length&&!element.disabled&&"
      + "element.textContent.trim()==="
      + json.dumps(label)
      + ");if(!target)return null;"
    )
    position = None
    for _ in range(12):
      target_geometry = self.evaluate(
        "(() => {" + find_target + "const bounds=target.getBoundingClientRect();"
        "const x=bounds.x+bounds.width/2,y=bounds.y+bounds.height/2;"
        "const hit=document.elementFromPoint(x,y);"
        "if(x>=0&&y>=0&&x<innerWidth&&y<innerHeight&&target.contains(hit))"
        "return {is_ready:true,x:x*devicePixelRatio,y:y*devicePixelRatio};"
        "let owner=target.parentElement;while(owner){"
        "if(/auto|scroll/.test(getComputedStyle(owner).overflowY)"
        "&&owner.scrollHeight>owner.clientHeight)break;owner=owner.parentElement;}"
        "if(!owner)return null;const clip=owner.getBoundingClientRect();"
        "return {is_ready:false,x:clip.left+Math.min(8,clip.width/2),"
        "y:clip.top+clip.height/2,deltaY:Math.sign(y-clip.top-clip.height/2)*"
        "Math.min(300,Math.max(1,Math.abs(y-clip.top-clip.height/2)))};})()"
      )
      self.assertIsNotNone(target_geometry, f"unreachable native control: {label}")
      if target_geometry["is_ready"]:
        position = self.evaluate(
          "(async () => {"
          + find_target
          + "const before=target.getBoundingClientRect();"
          "await new Promise(resolve=>requestAnimationFrame("
          "()=>requestAnimationFrame(resolve)));"
          "const bounds=target.getBoundingClientRect();"
          "const x=bounds.x+bounds.width/2,y=bounds.y+bounds.height/2;"
          "if(Math.abs(bounds.x-before.x)>0.5||Math.abs(bounds.y-before.y)>0.5"
          "||!target.contains(document.elementFromPoint(x,y)))return null;"
          "return {x:x*devicePixelRatio,y:y*devicePixelRatio};})()"
        )
        if position:
          break
      else:
        self.call(
          "Input.dispatchMouseEvent",
          type="mouseWheel",
          x=target_geometry["x"],
          y=target_geometry["y"],
          deltaX=0,
          deltaY=target_geometry["deltaY"],
        )
      time.sleep(0.1)
    self.assertIsNotNone(position, f"unreachable native control: {label}")
    window = self.window(host)
    screen_position = win32gui.ClientToScreen(
      window, (round(position["x"]), round(position["y"]))
    )
    original_cursor = win32api.GetCursorPos()
    previous_event_count = self.evaluate("window.__nativeControlEvents.length")
    is_button_down = False
    try:
      win32api.SetCursorPos(screen_position)
      hit_window = win32gui.GetAncestor(win32gui.WindowFromPoint(screen_position), 2)
      (self.artifacts / "native-control-target.json").write_text(
        json.dumps(
          {
            "label": label,
            "position": screen_position,
            "expected_window": window,
            "hit_window": hit_window,
            "hit_class": win32gui.GetClassName(hit_window),
            "owned_window_rect": win32gui.GetWindowRect(window),
            "hit_window_rect": win32gui.GetWindowRect(hit_window),
            "foreground_window": win32gui.GetForegroundWindow(),
          },
          ensure_ascii=False,
          indent=2,
        ),
        encoding="utf-8",
      )
      self.assertEqual(hit_window, window)
      win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
      is_button_down = True
      time.sleep(0.05)
      win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
      is_button_down = False
    finally:
      try:
        if is_button_down:
          win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
      finally:
        win32api.SetCursorPos(original_cursor)
    wait_until(
      lambda: self.evaluate(
        "window.__nativeControlEvents.slice("
        + str(previous_event_count)
        + ").some(event=>event.type==='click'&&event.isTrusted&&event.target==="
        + json.dumps(label)
        + ")"
      )
    )
    return screen_position

  def finish_coexistence_workflow(
    self, host, startup_snapshot, thread_id, long_draft, label, keyboard_window=None
  ):
    stages = []

    def record_stage(phase, **facts):
      self.assertTrue(self.evaluate("Boolean(document.querySelector('.tray-notice'))"))
      if keyboard_window is not None:
        self.assertTrue(win32gui.IsWindowVisible(keyboard_window))
      stages.append(
        {
          "phase": phase,
          "layout": self.measure_layout(),
          "api_requests": self.evaluate("window.__coexistenceApiRequests"),
          "native_control_events": self.evaluate("window.__nativeControlEvents"),
          **facts,
        }
      )
      (self.artifacts / f"{label}-workflow.json").write_text(
        json.dumps(stages, ensure_ascii=False, indent=2), encoding="utf-8"
      )
      self.capture_native_frame(host, f"{label}-{phase}")

    first_run_id = self.users(startup_snapshot, thread_id)[0]["run_id"]
    (self.root / "allow-reading-stream").touch()
    wait_until(
      lambda: (
        self.evaluate("document.querySelector('.toolbar-badge').textContent")
        == "等待审批"
      )
    )
    self.click("刷新数据")
    wait_until(lambda: "审批请求已核实，等待处理。" in self.body())
    locate_position = self.click_native_control(
      host, ".composer-toolbar .primary-button", "处理审批"
    )
    wait_until(
      lambda: self.evaluate("document.activeElement.id") == "current-approval-status"
    )
    choice_position = self.click_native_control(host, ".approval-options label", "批准")
    wait_until(lambda: "全部动作已选择，核对后提交" in self.body())
    approval_position = self.click_native_control(
      host, ".approval-actions .primary-button", "提交决策"
    )
    wait_until(
      lambda: (
        self.evaluate("document.querySelector('.toolbar-badge').textContent")
        == "已完成"
      )
    )
    first_history = self.users(startup_snapshot, thread_id)
    self.assertEqual(len(first_history), 1)
    self.assertEqual(first_history[0]["run_id"], first_run_id)
    self.assertEqual(first_history[0]["run_status"], "completed")
    approval_posts = self.evaluate(
      "window.__coexistenceApiRequests.filter(request=>request.method==='POST'"
      "&&request.path.endsWith('/approval-decisions'))"
    )
    self.assertEqual(len(approval_posts), 1)
    self.assertEqual(self.draft(), long_draft)
    record_stage(
      "approval",
      run_id=first_run_id,
      history=first_history,
      positions=[locate_position, choice_position, approval_position],
    )
    (self.root / "allow-reading-stream").unlink()
    self.evaluate("window.__dropCoexistencePost=true;window.__failCoexistenceGets=3")
    send_position = self.click_native_control(
      host, ".composer-toolbar .primary-button", "发送"
    )
    wait_until(lambda: "自动恢复已停止" in self.body(), timeout=25)
    submitted_history = self.users(startup_snapshot, thread_id)
    self.assertEqual(len(submitted_history), 2)
    self.assertEqual(submitted_history[-1]["content"]["content"], long_draft)
    second_run_id = submitted_history[-1]["run_id"]
    self.assertNotEqual(second_run_id, first_run_id)
    next_draft = "等待恢复时保留的下一条草稿\n" * 30
    self.set_coexistence_draft(next_draft)
    self.home()
    reading_position = self.geometry()
    record_stage(
      "send", run_id=second_run_id, history=submitted_history, position=send_position
    )
    reconnect_position = self.click_native_control(
      host, '[aria-label="运行观察恢复"] button', "重新连接"
    )
    # The app-bar connection summary is intentionally hidden on narrow screens.
    # Recovery must remove its visible notice and reflect accepted observation.
    wait_until(
      lambda: self.evaluate(
        "document.querySelector('.app-connection').textContent.includes('观察已建立')"
        "&&!document.querySelector('[aria-label=\"运行观察恢复\"]')"
      )
    )
    recovered_snapshot = self.client.get(
      startup_snapshot["base_url"] + f"/api/threads/{thread_id}/runs/{second_run_id}"
    ).json()["data"]
    self.assertEqual(recovered_snapshot["status"], "running")
    self.assert_anchor(reading_position)
    self.assertEqual(self.draft(), next_draft)
    self.assertEqual(self.evaluate("window.__sends.length"), 2)
    stream_requests = self.evaluate("window.__coexistenceRequests")
    second_run_requests = [
      request
      for request in stream_requests
      if request["path"].endswith(f"/runs/{second_run_id}/stream")
    ]
    self.assertEqual(sum(request["method"] == "POST" for request in stream_requests), 2)
    self.assertEqual(
      [request["method"] for request in second_run_requests],
      ["GET", "GET", "GET", "GET"],
    )
    record_stage(
      "reconnect",
      run_id=second_run_id,
      position=reconnect_position,
      reading_position=reading_position,
      requests=stream_requests,
      second_run_requests=second_run_requests,
      run_snapshot=recovered_snapshot,
    )
    cancel_position = self.click_native_control(
      host, ".composer-toolbar .primary-button", "取消运行"
    )
    wait_until(lambda: self.evaluate("Boolean(document.querySelector('dialog[open]'))"))
    confirm_position = self.click_native_control(
      host, "dialog[open] button", "确认取消"
    )
    wait_until(
      lambda: (
        self.evaluate("document.querySelector('.toolbar-badge').textContent")
        == "已取消"
      )
    )
    final_history = self.users(startup_snapshot, thread_id)
    self.assertEqual(len(final_history), 2)
    self.assertEqual(final_history[-1]["run_id"], second_run_id)
    self.assertEqual(final_history[-1]["run_status"], "cancelled")
    cancel_posts = self.evaluate(
      "window.__coexistenceApiRequests.filter(request=>request.method==='POST'"
      "&&request.path.endsWith(" + json.dumps(f"/runs/{second_run_id}/cancel") + "))"
    )
    self.assertEqual(len(cancel_posts), 1)
    self.assertEqual(self.draft(), next_draft)
    record_stage(
      "cancel",
      run_id=second_run_id,
      history=final_history,
      positions=[cancel_position, confirm_position],
      draft=next_draft,
    )
    return stages

  def run_native_size_workflow(self, width, height):
    (self.root / "missing-tray-icon").touch()
    self.fixture.env["DESKTOP_TEST_READING_APPROVAL"] = "1"
    host, startup_snapshot, thread_id = self.start_empty()
    self.instrument_coexistence_faults()
    self.instrument_layout()
    layout = self.resize_window(host, width, height)
    if width == 390:
      layout = self.arrange_narrow_window_in_work_area(host, width, height)
    self.focus_native_window(host)
    # Narrow navigation removes session rows from the DOM. The composer is the
    # real sending entry and does not depend on an expanded session list.
    self.set_coexistence_draft(f"{width}×{height} 联合操作准备")
    self.click_native_control(host, ".composer-toolbar .primary-button", "发送")
    wait_until(lambda: "生成中" in self.body())
    long_draft = f"{width}×{height} 的下一条原文消息\n" * 30
    self.set_coexistence_draft(long_draft)
    self.home()
    stages = self.finish_coexistence_workflow(
      host, startup_snapshot, thread_id, long_draft, f"size-{width}"
    )
    self.record(
      layout=layout,
      startup_snapshot=startup_snapshot,
      thread_id=thread_id,
      stages=stages,
    )
    self.screenshot()
    win32gui.PostMessage(self.window(host), win32con.WM_CLOSE, 0, 0)
    self.assertEqual(host.wait(timeout=15), 0)

  def test_1440_native_send_approve_cancel_and_reconnect(self):
    self.run_native_size_workflow(1440, 900)

  def test_1280_native_send_approve_cancel_and_reconnect(self):
    self.run_native_size_workflow(1280, 800)

  def test_1024_native_send_approve_cancel_and_reconnect(self):
    self.run_native_size_workflow(1024, 768)

  def test_390_native_send_approve_cancel_and_reconnect(self):
    self.run_native_size_workflow(390, 844)
