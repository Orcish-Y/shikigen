"""Windows touch injection exercises real hit testing; not physical fingers."""

import ctypes
import json
import time
from ctypes import wintypes

import win32gui
from native_workflow_acceptance import NativeWorkflowAcceptance
from window_acceptance import wait_until


class PointerSnapshot(ctypes.Structure):
  # Layout: https://learn.microsoft.com/windows/win32/api/winuser/ns-winuser-pointer_info
  _fields_ = (
    ("pointer_type", wintypes.UINT),
    ("pointer_id", wintypes.UINT),
    ("frame_id", wintypes.UINT),
    ("flags", wintypes.UINT),
    ("source_device", wintypes.HANDLE),
    ("target_window", wintypes.HWND),
    ("pixel_location", wintypes.POINT),
    ("himetric_location", wintypes.POINT),
    ("pixel_location_raw", wintypes.POINT),
    ("himetric_location_raw", wintypes.POINT),
    ("timestamp", wintypes.DWORD),
    ("history_count", wintypes.UINT),
    ("input_value", wintypes.INT),
    ("key_states", wintypes.DWORD),
    ("performance_count", ctypes.c_uint64),
    ("button_change", wintypes.UINT),
  )


class TouchContact(ctypes.Structure):
  _fields_ = (
    ("pointer", PointerSnapshot),
    ("flags", wintypes.UINT),
    ("mask", wintypes.UINT),
    ("contact_rect", wintypes.RECT),
    ("contact_rect_raw", wintypes.RECT),
    ("orientation", wintypes.UINT),
    ("pressure", wintypes.UINT),
  )


class NativeTouchAcceptance(NativeWorkflowAcceptance):
  def inject_touch_path(self, host, css_points):
    window = self.window(host)
    origin_x, origin_y = win32gui.ClientToScreen(window, (0, 0))
    scale = self.evaluate("devicePixelRatio")
    screen_points = [
      (origin_x + round(x * scale), origin_y + round(y * scale)) for x, y in css_points
    ]
    for point in screen_points:
      self.assertEqual(
        win32gui.GetAncestor(win32gui.WindowFromPoint(point), 2),
        window,
        "touch path hits a foreign window; no input will be injected",
      )
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.InitializeTouchInjection.argtypes = (wintypes.UINT, wintypes.DWORD)
    user32.InitializeTouchInjection.restype = wintypes.BOOL
    user32.InjectTouchInput.argtypes = (wintypes.UINT, ctypes.POINTER(TouchContact))
    user32.InjectTouchInput.restype = wintypes.BOOL
    if not user32.InitializeTouchInjection(1, 3):
      raise ctypes.WinError(ctypes.get_last_error())
    contact = TouchContact()
    contact.pointer.pointer_type = 2  # PT_TOUCH
    contact.pointer.pointer_id = 0
    contact.mask = 7  # CONTACTAREA | ORIENTATION | PRESSURE
    contact.orientation = 90
    contact.pressure = 512
    is_contact_active = False
    last_successful_point = None
    try:
      for point_index, (x, y) in enumerate(screen_points):
        self.assertEqual(
          win32gui.GetAncestor(win32gui.WindowFromPoint((x, y)), 2),
          window,
          "touch target changed before this frame; aborting the gesture",
        )
        contact.pointer.pixel_location = wintypes.POINT(x, y)
        contact.contact_rect = wintypes.RECT(x - 2, y - 2, x + 2, y + 2)
        contact.pointer.flags = 0x6 | (0x10000 if point_index == 0 else 0x20000)
        if not user32.InjectTouchInput(1, ctypes.byref(contact)):
          raise ctypes.WinError(ctypes.get_last_error())
        is_contact_active = True
        last_successful_point = (x, y)
        time.sleep(0.02)
    finally:
      if is_contact_active:
        contact.pointer.pixel_location = wintypes.POINT(*last_successful_point)
        contact.pointer.flags = 0x40000  # POINTER_FLAG_UP
        if not user32.InjectTouchInput(1, ctypes.byref(contact)):
          raise ctypes.WinError(ctypes.get_last_error())
    return screen_points

  def touch_selector(self, host, selector):
    css_position = self.evaluate(
      "(() => {const target=[...document.querySelectorAll("
      + json.dumps(selector)
      + ")].find(element=>element.getClientRects().length);"
      "if(!target)return null;const bounds=target.getBoundingClientRect();"
      "return [bounds.x+bounds.width/2,bounds.y+bounds.height/2]})()"
    )
    self.assertIsNotNone(css_position, selector)
    return self.inject_touch_path(host, [css_position])

  def test_os_touch_menu_switch_close_and_long_content_scroll(self):
    host, startup_snapshot, thread_id = self.start_completed()
    self.resize_window(host, 390, 844)
    self.focus_native_window(host)
    self.set_draft("触控下保留的原文\n  缩进")
    self.evaluate("""(() => {
      window.__osTouchEvents=[];
      for(const type of ['pointerdown','pointerup','touchstart','touchend'])
        document.addEventListener(type,event=>window.__osTouchEvents.push({
          type,pointerType:event.pointerType,isTrusted:event.isTrusted,
          target:event.target.className}),true);
    })()""")
    touch_positions = [self.touch_selector(host, ".mobile-navigation")]
    wait_until(
      lambda: self.evaluate("document.querySelectorAll('dialog[open]').length") == 1
    )
    self.assertTrue(
      self.evaluate(
        "document.querySelector('.sidebar-switch button').ariaPressed==='true'"
      )
    )
    touch_positions.append(
      self.touch_selector(host, ".sidebar-switch button:nth-child(2)")
    )
    wait_until(
      lambda: self.evaluate(
        "document.querySelector('.sidebar-switch button:nth-child(2)')"
        ".ariaPressed==='true'"
      )
    )
    touch_positions.append(
      self.touch_selector(host, 'dialog[open] [aria-label="关闭"]')
    )
    wait_until(
      lambda: self.evaluate("document.querySelectorAll('dialog[open]').length") == 0
    )
    self.assertEqual(self.draft(), "触控下保留的原文\n  缩进")
    self.assertIsNone(self.measure_layout()["preference"])
    self.home()
    initial_scroll = self.evaluate("document.querySelector('.timeline').scrollTop")
    swipe_path = self.evaluate("""(() => {
      const bounds=document.querySelector('.timeline').getBoundingClientRect();
      return Array.from({length:9},(_,index)=>
        [bounds.x+bounds.width/2,bounds.y+bounds.height*.8-index*bounds.height*.065]);
    })()""")
    touch_positions.append(self.inject_touch_path(host, swipe_path))
    wait_until(
      lambda: (
        self.evaluate("document.querySelector('.timeline').scrollTop")
        > initial_scroll + 10
      )
    )
    touch_events = self.evaluate("window.__osTouchEvents")
    self.assertTrue(
      any(
        event["type"] == "pointerdown"
        and event.get("pointerType") == "touch"
        and event["isTrusted"]
        for event in touch_events
      )
    )
    self.assertTrue(
      any(
        event["type"] == "pointerup"
        and event.get("pointerType") == "touch"
        and event["isTrusted"]
        for event in touch_events
      )
    )
    self.record(
      startup_snapshot=startup_snapshot,
      thread_id=thread_id,
      touch_positions=touch_positions,
      touch_events=touch_events,
      final_layout=self.measure_layout(),
      scope="Windows InjectTouchInput through actual OS; not physical finger contact",
    )
    self.capture_native_frame(host, "os-touch")
    self.screenshot()
    self.quit(host)
    self.assertEqual(host.wait(timeout=15), 0)
