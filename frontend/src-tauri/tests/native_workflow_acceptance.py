"""Joint native evidence: decorated frames and real Windows input/clipboard."""

import ctypes
import hashlib
import json
import struct
import zlib
from ctypes import wintypes

import win32clipboard
import win32con
import win32gui
import win32ui
from responsive_navigation_acceptance import ResponsiveNavigationAcceptance
from window_acceptance import REPO, wait_until


class KeyboardInput(ctypes.Structure):
  _fields_ = (
    ("virtual_key", wintypes.WORD),
    ("scan_code", wintypes.WORD),
    ("flags", wintypes.DWORD),
    ("time", wintypes.DWORD),
    ("extra", ctypes.c_size_t),
  )


class MouseInput(ctypes.Structure):
  _fields_ = (
    ("x", wintypes.LONG),
    ("y", wintypes.LONG),
    ("mouse_data", wintypes.DWORD),
    ("flags", wintypes.DWORD),
    ("time", wintypes.DWORD),
    ("extra", ctypes.c_size_t),
  )


class InputPayload(ctypes.Union):
  _fields_ = (("keyboard", KeyboardInput), ("mouse", MouseInput))


class WindowsInput(ctypes.Structure):
  _fields_ = (("kind", wintypes.DWORD), ("payload", InputPayload))


class NativeWorkflowAcceptance(ResponsiveNavigationAcceptance):
  artifact_root = REPO / ".scratch/frontend-completion/ticket-23/native"

  def capture_native_frame(self, host, name):
    window = self.window(host)
    return self.capture_window_frame(window, name)

  def capture_window_frame(self, window, name, is_desktop_capture=False):
    left, top, right, bottom = win32gui.GetWindowRect(window)
    width, height = right - left, bottom - top
    if is_desktop_capture:
      self.assertTrue(win32gui.IsWindowVisible(window))
      for fraction_x in (0.05, 0.5, 0.95):
        for fraction_y in (0.05, 0.5, 0.95):
          screen_point = (
            left + round(width * fraction_x),
            top + round(height * fraction_y),
          )
          self.assertEqual(
            win32gui.GetAncestor(win32gui.WindowFromPoint(screen_point), 2),
            window,
            "screen capture target is obscured by another window",
          )
    dc_owner = 0 if is_desktop_capture else window
    window_dc = (
      win32gui.GetDC(dc_owner) if is_desktop_capture else win32gui.GetWindowDC(dc_owner)
    )
    source_dc = win32ui.CreateDCFromHandle(window_dc)
    memory_dc = source_dc.CreateCompatibleDC()
    bitmap = win32ui.CreateBitmap()
    bitmap.CreateCompatibleBitmap(source_dc, width, height)
    previous_bitmap = memory_dc.SelectObject(bitmap)
    try:
      if is_desktop_capture:
        memory_dc.BitBlt(
          (0, 0), (width, height), source_dc, (left, top), win32con.SRCCOPY
        )
        self.assertEqual(win32gui.GetWindowRect(window), (left, top, right, bottom))
      else:
        self.assertTrue(
          ctypes.windll.user32.PrintWindow(window, memory_dc.GetSafeHdc(), 2),
          "PrintWindow could not capture the decorated application window",
        )
      pixel_bytes = bitmap.GetBitmapBits(True)
      rgb_pixels = bytearray(width * height * 3)
      rgb_pixels[0::3] = pixel_bytes[2::4]
      rgb_pixels[1::3] = pixel_bytes[1::4]
      rgb_pixels[2::3] = pixel_bytes[0::4]
      self.assertGreater(len(set(rgb_pixels)), 1, "native frame is blank")
      rows = b"".join(
        b"\0" + rgb_pixels[row * width * 3 : (row + 1) * width * 3]
        for row in range(height)
      )

      def encode_png_chunk(chunk_type, payload):
        return (
          struct.pack(">I", len(payload))
          + chunk_type
          + payload
          + struct.pack(">I", zlib.crc32(chunk_type + payload))
        )

      (self.artifacts / f"{name}-native.png").write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + encode_png_chunk(
          b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
        )
        + encode_png_chunk(b"IDAT", zlib.compress(rows))
        + encode_png_chunk(b"IEND", b"")
      )
    finally:
      memory_dc.SelectObject(previous_bitmap)
      win32gui.DeleteObject(bitmap.GetHandle())
      memory_dc.DeleteDC()
      source_dc.DeleteDC()
      win32gui.ReleaseDC(dc_owner, window_dc)
    return {
      "title": win32gui.GetWindowText(window),
      "decorated": bool(
        win32gui.GetWindowLong(window, win32con.GWL_STYLE) & win32con.WS_CAPTION
      ),
      "window_rect": [left, top, right, bottom],
      "client_rect": list(win32gui.GetClientRect(window)),
      "frame_pixels": [width, height],
      "dpi": ctypes.windll.user32.GetDpiForWindow(window),
      "capture": (
        "Win32 desktop BitBlt restricted to the visible, verified target rect"
        if is_desktop_capture
        else "Win32 PrintWindow PW_RENDERFULLCONTENT; includes native title bar"
      ),
    }

  def send_windows_inputs(self, keyboard_inputs):
    input_array = (WindowsInput * len(keyboard_inputs))(
      *(
        WindowsInput(1, InputPayload(keyboard=keyboard_input))
        for keyboard_input in keyboard_inputs
      )
    )
    send_input = ctypes.windll.user32.SendInput
    send_input.argtypes = (wintypes.UINT, ctypes.POINTER(WindowsInput), ctypes.c_int)
    send_input.restype = wintypes.UINT
    self.assertEqual(
      send_input(len(input_array), input_array, ctypes.sizeof(WindowsInput)),
      len(input_array),
    )

  def type_windows_text(self, text):
    for line_index, line in enumerate(text.split("\n")):
      if line_index:
        self.press_windows_keys(win32con.VK_SHIFT, win32con.VK_RETURN)
      utf16_text = line.encode("utf-16-le")
      keyboard_inputs = []
      for offset in range(0, len(utf16_text), 2):
        code_unit = int.from_bytes(utf16_text[offset : offset + 2], "little")
        keyboard_inputs.extend(
          (KeyboardInput(0, code_unit, 4, 0, 0), KeyboardInput(0, code_unit, 6, 0, 0))
        )
      if keyboard_inputs:
        self.send_windows_inputs(keyboard_inputs)

  def press_windows_keys(self, *virtual_keys):
    self.send_windows_inputs(
      [KeyboardInput(key, 0, 0, 0, 0) for key in virtual_keys]
      + [KeyboardInput(key, 0, 2, 0, 0) for key in reversed(virtual_keys)]
    )

  def snapshot_clipboard_formats(self):
    """Materialize restorable formats before any native copy overwrites them."""
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GlobalSize.argtypes = (wintypes.HGLOBAL,)
    kernel.GlobalSize.restype = ctypes.c_size_t
    kernel.GlobalLock.argtypes = (wintypes.HGLOBAL,)
    kernel.GlobalLock.restype = ctypes.c_void_p
    kernel.GlobalUnlock.argtypes = (wintypes.HGLOBAL,)
    clipboard_formats = {}
    win32clipboard.OpenClipboard()
    try:
      format_id = win32clipboard.EnumClipboardFormats(0)
      while format_id:
        self.assertNotIn(
          format_id,
          {2, 3, 9, 14, 0x80, 0x82, 0x83, 0x8E},
          "non-memory clipboard format cannot be safely restored by this probe",
        )
        memory_handle = win32clipboard.GetClipboardDataHandle(format_id)
        memory_size = kernel.GlobalSize(memory_handle)
        self.assertGreater(memory_size, 0, "clipboard format is not materialized")
        memory_pointer = kernel.GlobalLock(memory_handle)
        self.assertTrue(memory_pointer)
        try:
          clipboard_formats[format_id] = ctypes.string_at(memory_pointer, memory_size)
        finally:
          kernel.GlobalUnlock(memory_handle)
        format_id = win32clipboard.EnumClipboardFormats(format_id)
    finally:
      win32clipboard.CloseClipboard()
    return clipboard_formats

  def test_four_css_sizes_capture_native_titlebar_and_original_desktop_states(self):
    host, startup_snapshot, thread_id = self.start_completed()
    captures = []
    for width, height in ((1440, 900), (1280, 800), (1024, 768), (390, 844)):
      layout = self.resize_window(host, width, height)
      self.capture_size(f"{width}-workspace", layout)
      frame = self.capture_native_frame(host, str(width))
      self.assertEqual(frame["title"], "Shikigen")
      self.assertTrue(frame["decorated"])
      self.assertEqual(
        frame["client_rect"][2:],
        [round(width * layout["dpr"]), round(height * layout["dpr"])],
      )
      captures.append({"layout": layout, "native_frame": frame})
      if width == 1440:
        self.click_selector('.workspace > .navigation [aria-label="收起主导航"]')
        wait_until(lambda: self.measure_layout()["navigation"]["width"] == 64)
        self.capture_size("1440-collapsed-workspace")
        self.capture_native_frame(host, "1440-collapsed")
    self.record(
      startup_snapshot=startup_snapshot, thread_id=thread_id, captures=captures
    )
    self.quit(host)
    self.assertEqual(host.wait(timeout=15), 0)

  def test_windows_sendinput_original_enter_and_global_modal_focus(self):
    host, startup_snapshot, thread_id = self.start_empty()
    (self.root / "allow-reading-stream").touch()
    window = self.focus_native_window(host)
    self.evaluate("document.querySelector('#message-draft').focus()")
    self.evaluate(
      "window.__nativeKeys=[];document.addEventListener('keydown',event=>"
      "window.__nativeKeys.push({key:event.key,isTrusted:event.isTrusted,isComposing:event.isComposing}),true)"
    )
    original_text = "  Windows 原文输入\n缩进保留  "
    self.type_windows_text(original_text)
    wait_until(
      lambda: (
        self.evaluate("document.querySelector('#message-draft').value") == original_text
      )
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
    self.assertEqual(
      sum(
        message["content"].get("content") == original_text
        for message in message_history
      ),
      1,
    )
    self.press_windows_keys(win32con.VK_CONTROL, ord("K"))
    wait_until(lambda: self.evaluate("document.activeElement?.id") == "command-search")
    self.press_windows_keys(win32con.VK_ESCAPE)
    wait_until(
      lambda: self.evaluate("document.querySelectorAll('dialog[open]').length") == 0
    )
    keyboard_events = self.evaluate("window.__nativeKeys")
    self.assertTrue(
      any(event["key"] == "Enter" and event["isTrusted"] for event in keyboard_events)
    )
    self.record(
      startup_snapshot=startup_snapshot,
      thread_id=thread_id,
      message_history=message_history,
      foreground_window=window,
      keyboard_events=keyboard_events,
      scope=(
        "Windows SendInput reaches real WebView; injected OS input, "
        "not human physical keyboard or OS IME candidates"
      ),
    )
    self.screenshot()
    self.quit(host)
    self.assertEqual(host.wait(timeout=15), 0)

  def test_real_system_clipboard_receives_complete_message_without_mock(self):
    host, startup_snapshot, thread_id = self.start_completed()
    self.focus_native_window(host)
    self.assertTrue(
      self.evaluate(
        "navigator.clipboard.writeText.toString().includes('[native code]')"
      )
    )
    assistant_text = self.evaluate(
      "document.querySelector('article.assistant .plain-content')?.textContent"
    )
    message_history = self.client.get(
      startup_snapshot["base_url"] + f"/api/threads/{thread_id}/messages"
    ).json()["data"]
    assistant_body = next(
      message["content"]["content"]
      for message in reversed(message_history)
      if message["content"].get("type") == "ai"
    )
    expected_clipboard_text = (
      assistant_body
      if isinstance(assistant_body, str)
      else json.dumps(assistant_body, ensure_ascii=False, indent=2)
    )

    def read_clipboard_text():
      win32clipboard.OpenClipboard()
      try:
        return (
          win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
          if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT)
          else None
        )
      finally:
        win32clipboard.CloseClipboard()

    original_formats = self.snapshot_clipboard_formats()
    original_text = read_clipboard_text()
    is_clipboard_restored = False

    def restore_clipboard():
      nonlocal is_clipboard_restored
      if is_clipboard_restored:
        return
      win32clipboard.OpenClipboard(self.window(host))
      try:
        win32clipboard.EmptyClipboard()
        for format_id, format_payload in original_formats.items():
          win32clipboard.SetClipboardData(format_id, memoryview(format_payload))
      finally:
        win32clipboard.CloseClipboard()
      restored_formats = self.snapshot_clipboard_formats()
      for format_id, format_payload in original_formats.items():
        self.assertEqual(restored_formats.get(format_id), format_payload)
      is_clipboard_restored = True

    self.addCleanup(restore_clipboard)
    self.click_selector('article.assistant:last-of-type [aria-label="复制完整内容"]')
    # CF_UNICODETEXT uses CR-LF; compare the complete OS representation.
    # https://learn.microsoft.com/windows/win32/dataxchg/standard-clipboard-formats
    expected_windows_text = expected_clipboard_text.replace("\r\n", "\n").replace(
      "\n", "\r\n"
    )
    try:
      clipboard_text = wait_until(
        lambda: read_clipboard_text() == expected_windows_text and read_clipboard_text()
      )
    except AssertionError:
      observed_text = read_clipboard_text()
      (self.artifacts / "clipboard-comparison.json").write_text(
        json.dumps(
          {
            "expected_sha256": hashlib.sha256(
              expected_windows_text.encode()
            ).hexdigest(),
            "observed_sha256": hashlib.sha256(observed_text.encode()).hexdigest()
            if observed_text is not None
            else None,
            "expected_length": len(expected_windows_text),
            "observed_length": len(observed_text)
            if observed_text is not None
            else None,
            "observed_crlf_count": observed_text.count("\r\n")
            if observed_text is not None
            else None,
            "observed_lf_count": observed_text.count("\n")
            if observed_text is not None
            else None,
          },
          indent=2,
        ),
        encoding="utf-8",
      )
      raise
    self.assertEqual(clipboard_text, expected_windows_text)
    restore_clipboard()
    self.assertEqual(read_clipboard_text(), original_text)
    self.record(
      startup_snapshot=startup_snapshot,
      thread_id=thread_id,
      assistant_text=assistant_text,
      clipboard_text=clipboard_text,
      original_clipboard_restored=True,
      scope=(
        "unmodified navigator.clipboard and Windows CF_UNICODETEXT; "
        "complete persisted message"
      ),
    )
    self.screenshot()
    self.quit(host)
    self.assertEqual(host.wait(timeout=15), 0)
