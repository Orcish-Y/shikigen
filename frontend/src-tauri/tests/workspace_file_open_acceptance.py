"""第15票：公开原生命令、真实资源/Run 与每次文件确认。"""

import ctypes
import json
import unittest

import win32api
import win32con
import win32gui
import win32process
from window_acceptance import REPO, wait_until
from workspace_image_acceptance import WorkspaceImageAcceptance


class WorkspaceFileOpenAcceptance(WorkspaceImageAcceptance):
  artifact_root = REPO / ".scratch/frontend-completion/ticket-15/native"

  def start_file_conversation(self):
    host, startup_snapshot, thread = self.start_empty()
    self.call("Page.enable")
    self.call(
      "Page.addScriptToEvaluateOnNewDocument",
      source="""
      window.__fileCommands=[];
      const performFetch=window.fetch.bind(window);
      window.fetch=async(url,options)=>{
        const command=String(url).replace('http://ipc.localhost/','');
        const isFileCommand=['prepare_workspace_file_open',
          'open_prepared_workspace_file',
          'discard_prepared_workspace_file'].includes(command);
        const invocation=isFileCommand?{command,args:JSON.parse(options.body)}:null;
        if(invocation) window.__fileCommands.push(invocation);
        const response=await performFetch(url,options);
        if(invocation) {
          invocation.response=await response.clone().json();
          invocation.resultType=response.headers.get('Tauri-Response');
        }
        return response;
      };
      """,
    )
    self.call("Page.reload")
    wait_until(lambda: self.evaluate("Array.isArray(window.__fileCommands)"))
    wait_until(lambda: "从一个想法开始" in self.body())
    self.send("本地文件打开验收")
    wait_until(lambda: "图片正文结束" in self.body())
    wait_until(lambda: self.loaded_count() == 4)
    return host, startup_snapshot, thread

  def click_report(self):
    self.evaluate(
      "(() => {const button=[...document.querySelectorAll('[data-file-reference]')]"
      ".find(e=>e.dataset.fileReference==='notes/report.txt');button.focus();button.click();})()"
    )
    wait_until(lambda: "打开本地文件？" in self.body())
    wait_until(
      lambda: self.evaluate(
        "[...document.querySelectorAll('dialog[open] button')]"
        ".some(e=>e.textContent==='确认打开'&&!e.disabled)"
      )
    )

  def invoke_native_command(self, command, command_arguments):
    return self.evaluate(
      "window.__TAURI_INTERNALS__.invoke("
      + json.dumps(command)
      + ","
      + json.dumps(command_arguments)
      + ").then(value=>({value}),error=>({error}))"
    )

  def close_prompt(self):
    self.click("取消")
    wait_until(
      lambda: self.evaluate("document.querySelectorAll('dialog[open]').length") == 0
    )

  def read_file_invocations(self):
    return self.evaluate("window.__fileCommands")

  def read_message_history(self, startup_snapshot, thread):
    return self.client.get(
      startup_snapshot["base_url"] + f"/api/threads/{thread}/messages"
    ).json()["data"]

  def test_each_click_default_cancel_copy_escape_backdrop_and_focus_never_open(self):
    host, startup_snapshot, thread = self.start_file_conversation()
    message_history = self.read_message_history(startup_snapshot, thread)
    self.click_report()
    self.assertEqual(self.evaluate("document.activeElement.id"), "cancel-file-open")
    self.assertEqual(
      self.evaluate("document.querySelectorAll('dialog[open]').length"), 1
    )
    self.assertIn(str(self.workspace / "notes/report.txt"), self.body())
    self.evaluate(
      "Object.defineProperty(navigator,'clipboard',{configurable:true,"
      "value:{writeText:async text=>window.__copied=text}})"
    )
    self.click("复制完整路径")
    self.assertEqual(
      self.evaluate("window.__copied"), str(self.workspace / "notes/report.txt")
    )
    self.screenshot()
    self.close_prompt()
    self.assertEqual(
      self.evaluate("document.activeElement.dataset.fileReference"), "notes/report.txt"
    )
    self.click_report()
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
      lambda: self.evaluate("document.querySelectorAll('dialog[open]').length") == 0
    )
    self.click_report()
    self.evaluate(
      "document.querySelector('dialog[open]').dispatchEvent(new MouseEvent("
      "'click',{bubbles:true,clientX:0,clientY:0}))"
    )
    wait_until(
      lambda: self.evaluate("document.querySelectorAll('dialog[open]').length") == 0
    )
    self.click_report()
    self.evaluate("document.querySelector('dialog[open] [aria-label=关闭]').click()")
    wait_until(
      lambda: self.evaluate("document.querySelectorAll('dialog[open]').length") == 0
    )
    file_invocations = self.read_file_invocations()
    self.assertEqual(
      sum(
        command["command"] == "prepare_workspace_file_open"
        for command in file_invocations
      ),
      4,
    )
    self.assertFalse(
      any(
        command["command"] == "open_prepared_workspace_file"
        for command in file_invocations
      )
    )
    request_ids = [
      command["response"]["request_id"]
      for command in file_invocations
      if command["command"] == "prepare_workspace_file_open"
    ]
    self.assertEqual(len(set(request_ids)), 4)
    for request_id in request_ids:
      self.assertEqual(
        self.invoke_native_command(
          "open_prepared_workspace_file", {"requestId": request_id}
        )["error"]["code"],
        "invalid_file_intent",
      )
    self.assertEqual(
      self.read_message_history(startup_snapshot, thread), message_history
    )
    self.record(file_invocations=file_invocations, message_history=message_history)
    self.quit(host)
    self.assertEqual(host.wait(timeout=15), 0)

  def test_changed_file_fails_then_manual_prepare_reconfirms_current_metadata(self):
    host, startup_snapshot, thread = self.start_file_conversation()
    message_history = self.read_message_history(startup_snapshot, thread)
    self.click_report()
    old_intent = next(
      command["response"]
      for command in self.read_file_invocations()
      if command["command"] == "prepare_workspace_file_open"
    )
    (self.workspace / "notes/report.txt").write_text(
      "文件版本已更新，需要新的确认。", encoding="utf-8"
    )
    self.click("确认打开")
    wait_until(lambda: "文件路径、版本或工作目录已变化" in self.body())
    self.assertFalse(
      self.evaluate(
        "[...document.querySelectorAll('dialog[open] button')]"
        ".some(e=>e.textContent==='确认打开')"
      )
    )
    self.click("重新准备")
    wait_until(
      lambda: self.evaluate(
        "[...document.querySelectorAll('dialog[open] button')]"
        ".some(e=>e.textContent==='确认打开'&&!e.disabled)"
      )
    )
    updated_confirmation = [
      command["response"]
      for command in self.read_file_invocations()
      if command["command"] == "prepare_workspace_file_open"
    ][-1]
    self.assertNotEqual(updated_confirmation["version"], old_intent["version"])
    self.assertNotEqual(updated_confirmation["request_id"], old_intent["request_id"])
    self.assertEqual(
      sum(
        command["command"] == "open_prepared_workspace_file"
        for command in self.read_file_invocations()
      ),
      1,
    )
    self.close_prompt()
    self.assertEqual(
      self.read_message_history(startup_snapshot, thread), message_history
    )
    self.record(
      file_invocations=self.read_file_invocations(),
      message_history=message_history,
    )
    self.screenshot()
    self.quit(host)
    self.assertEqual(host.wait(timeout=15), 0)

  def test_public_commands_reject_outside_directory_old_lease_and_generic_opener(self):
    host, startup_snapshot, thread = self.start_file_conversation()
    errors = []
    for reference in (
      "../outside.png",
      "notes",
      "notes/missing.txt",
      "javascript:alert(1)",
    ):
      response = self.invoke_native_command(
        "prepare_workspace_file_open",
        {
          "startupId": startup_snapshot["startup_id"],
          "path": reference,
          "baseUrl": "http://example.org",
          "root": "C:\\",
        },
      )
      self.assertIn("error", response)
      errors.append(response)
    self.assertIn("HTTP 403", errors[0]["error"]["message"])
    self.assertIn("HTTP 422", errors[1]["error"]["message"])
    self.assertIn("HTTP 404", errors[2]["error"]["message"])
    old_lease_response = self.invoke_native_command(
      "prepare_workspace_file_open",
      {"startupId": "old-startup", "path": "notes/report.txt"},
    )
    self.assertEqual(old_lease_response["error"]["code"], "stale_backend_lease")
    permission_response = self.invoke_native_command(
      "plugin:opener|open_path", {"path": str(self.workspace / "notes/report.txt")}
    )
    self.assertIn("not allowed", permission_response["error"])
    self.record(
      errors=errors,
      old_lease_response=old_lease_response,
      permission_response=permission_response,
      message_history=self.read_message_history(startup_snapshot, thread),
    )
    self.quit(host)
    self.assertEqual(host.wait(timeout=15), 0)

  def test_switch_hide_lease_loss_and_reference_change_close_confirmation(self):
    host, startup_snapshot, thread = self.start_file_conversation()
    self.click_report()
    # Reference mutation represents a streamed link replacement at the rendered UI seam.
    self.evaluate(
      "document.querySelector('[data-file-reference=\"notes/report.txt\"]').dataset.fileReference='notes/replaced.txt'"
    )
    wait_until(
      lambda: self.evaluate("document.querySelectorAll('dialog[open]').length") == 0
    )
    self.evaluate(
      "document.querySelector('[data-file-reference=\"notes/replaced.txt\"]').dataset.fileReference='notes/report.txt'"
    )
    self.click_report()
    win32gui.PostMessage(self.window(host), win32con.WM_CLOSE, 0, 0)
    wait_until(lambda: not win32gui.IsWindowVisible(self.window(host)))
    wait_until(
      lambda: self.evaluate("document.querySelectorAll('dialog[open]').length") == 0
    )
    self.tray_menu(host, "打开主窗口", native_command=True)
    wait_until(lambda: self.loaded_count() == 4)
    self.click_report()
    # Programmatic selection covers invalidation; physical clicks are not made
    # behind a modal.
    self.evaluate(
      "[...document.querySelectorAll('button')].find(e=>e.textContent.trim()==='新建').click()"
    )
    wait_until(
      lambda: self.evaluate("document.querySelectorAll('dialog[open]').length") == 0
    )
    wait_until(
      lambda: (
        self.evaluate(
          "document.querySelector('.session[aria-current=true]')?.dataset.conversationId"
        )
        not in (None, thread)
      )
    )
    self.select_thread(thread)
    wait_until(lambda: self.loaded_count() == 4)
    self.click_report()
    lease_frame = {
      **startup_snapshot,
      "startup_id": "file-open-lease-fixture",
      "revision": startup_snapshot["revision"] + 100,
    }
    self.invoke_native_command(
      "plugin:event|emit", {"event": "backend-state-changed", "payload": lease_frame}
    )
    wait_until(
      lambda: self.evaluate("document.querySelectorAll('dialog[open]').length") == 0
    )
    self.assertFalse(
      any(
        command["command"] == "open_prepared_workspace_file"
        for command in self.read_file_invocations()
      )
    )
    self.record(
      file_invocations=self.read_file_invocations(),
      lease_frame=lease_frame,
      scope="公开桥接帧；非实际 BackendManager 重启",
    )
    self.quit(host)
    self.assertEqual(host.wait(timeout=15), 0)

  def test_image_system_open_replaces_detail_with_one_fresh_confirmation(self):
    host, startup_snapshot, thread = self.start_file_conversation()
    self.evaluate(
      "(() => {const button=document.querySelector("
      "'.workspace-image .content-actions button');"
      "button.focus();button.click();})()"
    )
    wait_until(
      lambda: self.evaluate("Boolean(document.querySelector('.image-viewer'))")
    )
    self.evaluate(
      "(() => {const button=document.querySelector("
      "'.image-viewer [data-file-reference]');button.focus();button.click();})()"
    )
    wait_until(lambda: "打开本地文件？" in self.body())
    wait_until(
      lambda: (
        "tall.png" in self.evaluate("document.querySelector('dialog[open]').innerText")
      )
    )
    self.assertEqual(
      self.evaluate("document.querySelectorAll('dialog[open]').length"), 1
    )
    self.assertEqual(self.evaluate("document.activeElement.id"), "cancel-file-open")
    self.assertEqual(self.read_file_invocations()[0]["args"]["path"], "images/tall.png")
    self.close_prompt()
    self.assertFalse(
      any(
        command["command"] == "open_prepared_workspace_file"
        for command in self.read_file_invocations()
      )
    )
    self.record(file_invocations=self.read_file_invocations())
    self.screenshot()
    self.quit(host)
    self.assertEqual(host.wait(timeout=15), 0)

  def test_source_message_identity_and_real_backend_failure_revoke_and_restore_focus(
    self,
  ):
    host, startup_snapshot, thread = self.start_file_conversation()
    self.click_report()
    first_request_id = self.read_file_invocations()[0]["response"]["request_id"]
    # Another message still links the same file. It must not keep the original
    # message's confirmation alive when that message is replaced.
    self.evaluate(
      "(() => {const source=document.querySelector("
      "'[data-file-reference=\"notes/report.txt\"]');"
      "const otherReferenceElement=source.cloneNode(true);"
      "otherReferenceElement.dataset.fileMessageIdentity='other-message';"
      "source.parentElement.append(otherReferenceElement);"
      "window.__originalFileMessageIdentity=source.dataset.fileMessageIdentity;"
      "source.dataset.fileMessageIdentity='replacement-message';})()"
    )
    wait_until(
      lambda: self.evaluate("document.querySelectorAll('dialog[open]').length") == 0
    )
    self.assertEqual(
      self.invoke_native_command(
        "open_prepared_workspace_file", {"requestId": first_request_id}
      )["error"]["code"],
      "invalid_file_intent",
    )
    self.evaluate(
      "document.querySelector('[data-file-message-identity=other-message]').remove();"
      "document.querySelector('[data-file-message-identity=replacement-message]')"
      ".dataset.fileMessageIdentity=window.__originalFileMessageIdentity"
    )
    self.click_report()
    second_request_id = self.read_file_invocations()[-1]["response"]["request_id"]
    backend_process_handles = self.fixture.process_handles()
    win32api.TerminateProcess(backend_process_handles[0], 73)
    wait_until(lambda: self.snapshot().get("can_retry"))
    wait_until(lambda: "后端启动或运行失败" in self.body())
    wait_until(
      lambda: self.evaluate("document.querySelectorAll('dialog[open]').length") == 0
    )
    self.assertTrue(
      self.evaluate("document.activeElement.matches('.backend-screen')"),
      "lost backend must return focus to a connected stable status page",
    )
    self.assertEqual(
      self.invoke_native_command(
        "open_prepared_workspace_file", {"requestId": second_request_id}
      )["error"]["code"],
      "invalid_file_intent",
    )
    self.assertFalse(
      any(
        invocation["command"] == "open_prepared_workspace_file"
        and invocation.get("response") is True
        for invocation in self.read_file_invocations()
      )
    )
    self.record(
      file_invocations=self.read_file_invocations(),
      actual_focus=self.evaluate("document.activeElement.outerHTML"),
      scope="原消息替换保留同路径另一引用；实际自管后端进程失败",
    )
    self.screenshot()
    self.quit(host)
    self.assertEqual(host.wait(timeout=15), 0)

  def test_explicit_confirmation_reaches_actual_default_program_once(self):
    host, startup_snapshot, thread = self.start_file_conversation()
    message_history = self.read_message_history(startup_snapshot, thread)
    windows_before = self.read_window_titles()
    self.click_report()
    self.click("确认打开")
    wait_until(lambda: "系统已接受打开请求" in self.body())
    file_invocations = self.read_file_invocations()
    self.assertEqual(
      sum(
        command["command"] == "open_prepared_workspace_file"
        for command in file_invocations
      ),
      1,
    )
    self.assertIs(
      next(
        command["response"]
        for command in file_invocations
        if command["command"] == "open_prepared_workspace_file"
      ),
      True,
    )
    # Actual OS window evidence, with ownership-limited cleanup. Do not close an
    # existing user's editor/window if the default app reuses one.
    opened_window_titles = wait_until(
      lambda: {
        hwnd: title
        for hwnd, title in self.read_window_titles().items()
        if "report" in title.lower() and windows_before.get(hwnd) != title
      }
    )
    for hwnd in opened_window_titles:
      if hwnd not in windows_before:
        self.addCleanup(win32gui.PostMessage, hwnd, win32con.WM_CLOSE, 0, 0)
    self.assertEqual(
      self.read_message_history(startup_snapshot, thread), message_history
    )
    request_id = next(
      command["response"]["request_id"]
      for command in file_invocations
      if command["command"] == "prepare_workspace_file_open"
    )
    self.assertEqual(
      self.invoke_native_command(
        "open_prepared_workspace_file", {"requestId": request_id}
      )["error"]["code"],
      "invalid_file_intent",
    )
    self.record(
      file_invocations=file_invocations,
      opened_windows=opened_window_titles,
      message_history=message_history,
      scope="实际系统默认程序；不宣称应用已读完文件",
    )
    self.screenshot()
    self.click("关闭")
    self.quit(host)
    self.assertEqual(host.wait(timeout=15), 0)

  def test_unassociated_file_uses_actual_os_result_and_never_reuses_confirmation(self):
    host, startup_snapshot, thread = self.start_file_conversation()
    # A unique, unregistered extension avoids changing the user's associations.
    extension = "shikigen_unassociated_" + self.root.parent.name.replace(" ", "_")
    file_path = self.workspace / ("no-default." + extension)
    file_path.write_text("没有默认程序的原生验收", encoding="utf-8")
    # Verify the actual Windows association, without changing registry settings.
    # SDK Shlwapi.h: INIT_IGNOREUNKNOWN=0x400, ASSOCSTR_EXECUTABLE=2.
    query_file_association = ctypes.WinDLL("shlwapi").AssocQueryStringW
    query_file_association.argtypes = [
      ctypes.c_uint,
      ctypes.c_uint,
      ctypes.c_wchar_p,
      ctypes.c_wchar_p,
      ctypes.c_wchar_p,
      ctypes.POINTER(ctypes.c_uint),
    ]
    query_file_association.restype = ctypes.c_long
    executable_buffer = ctypes.create_unicode_buffer(32768)
    executable_capacity = ctypes.c_uint(len(executable_buffer))
    association_hresult = query_file_association(
      0x400,
      2,
      "." + extension,
      None,
      executable_buffer,
      ctypes.byref(executable_capacity),
    )
    self.assertLess(
      association_hresult, 0, "fixture extension has a default executable"
    )
    self.assertEqual(executable_buffer.value, "")
    file_confirmation = self.invoke_native_command(
      "prepare_workspace_file_open",
      {"startupId": startup_snapshot["startup_id"], "path": str(file_path)},
    )["value"]
    windows_before = self.read_window_titles(include_hidden=True)
    self.evaluate(
      "window.__noDefaultResult=null;"
      "window.__TAURI_INTERNALS__.invoke('open_prepared_workspace_file',"
      + json.dumps({"requestId": file_confirmation["request_id"]})
      + ").then(value=>window.__noDefaultResult={value},"
      "error=>window.__noDefaultResult={error}); 'started'"
    )
    chooser_windows = {}
    observed_windows = {}

    def read_chooser_windows():
      for hwnd, title in self.read_window_titles(include_hidden=True).items():
        if hwnd in windows_before:
          continue
        _, process_id = win32process.GetWindowThreadProcessId(hwnd)
        process_path = ""
        try:
          process_handle = win32api.OpenProcess(
            win32con.PROCESS_QUERY_INFORMATION | win32con.PROCESS_VM_READ,
            False,
            process_id,
          )
          try:
            process_path = win32process.GetModuleFileNameEx(process_handle, 0)
          finally:
            process_handle.Close()
        except Exception as error:
          process_path = "query unavailable: " + str(error)
        child_labels = []

        def collect_child_label(child_hwnd, _, child_labels=child_labels):
          child_labels.append(win32gui.GetWindowText(child_hwnd))

        win32gui.EnumChildWindows(hwnd, collect_child_label, None)
        window_facts = {
          "title": title,
          "class": win32gui.GetClassName(hwnd),
          "process_id": process_id,
          "process_path": process_path,
          "child_labels": child_labels,
          "is_visible": bool(win32gui.IsWindowVisible(hwnd)),
        }
        observed_windows[hwnd] = window_facts
        if extension.lower() in (title + " ".join(child_labels)).lower() or (
          process_path.lower().endswith("\\openwith.exe")
          and window_facts["class"] == "Open With Dummy Window Class For Interim Dialog"
        ):
          chooser_windows[hwnd] = window_facts
      return chooser_windows

    def read_open_outcome():
      read_chooser_windows()
      response = self.evaluate("window.__noDefaultResult")
      if response is not None:
        return response
      return None

    response = wait_until(read_open_outcome, timeout=15)
    if "error" in response:
      self.assertEqual(response["error"]["code"], "file_open_failed")
      self.assertTrue(response["error"]["message"])
    else:
      # ShellExecute can accept the OpenWith dispatch. Its dummy host window may
      # be hidden; retain visibility as evidence, never claim a visible chooser
      # or a default program from the host window alone.
      self.assertIs(response["value"], True)
      try:
        wait_until(read_chooser_windows, timeout=10)
      finally:
        (self.artifacts / "system-windows.json").write_text(
          json.dumps(observed_windows, ensure_ascii=False, indent=2),
          encoding="utf-8",
        )
      self.assertTrue(chooser_windows, "unassociated acceptance needs chooser evidence")
    # Only fresh, identified chooser windows are ours to close.
    for hwnd in chooser_windows:
      if win32gui.IsWindow(hwnd):
        win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
    self.assertEqual(
      self.invoke_native_command(
        "open_prepared_workspace_file", {"requestId": file_confirmation["request_id"]}
      )["error"]["code"],
      "invalid_file_intent",
    )
    self.record(
      file_confirmation=file_confirmation,
      actual_os_response=response,
      chooser_windows=chooser_windows,
      association_hresult=association_hresult,
      default_executable=executable_buffer.value,
      scope="实际无默认关联与OpenWith派发；不宣称可见选择器或文件已显示",
    )
    self.quit(host)
    self.assertEqual(host.wait(timeout=15), 0)

  @staticmethod
  def read_window_titles(*, include_hidden=False):
    windows = {}

    def collect(hwnd, _):
      if include_hidden or win32gui.IsWindowVisible(hwnd):
        windows[hwnd] = win32gui.GetWindowText(hwnd)

    win32gui.EnumWindows(collect, None)
    return windows


if __name__ == "__main__":
  suite = unittest.TestSuite(
    WorkspaceFileOpenAcceptance(name)
    for name in WorkspaceFileOpenAcceptance.__dict__
    if name.startswith("test_")
  )
  result = unittest.TextTestRunner(verbosity=2).run(suite)
  raise SystemExit(0 if result.wasSuccessful() else 1)
