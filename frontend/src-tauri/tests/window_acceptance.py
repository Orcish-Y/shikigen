"""Shared real Windows window, tray, WebView and isolated-runtime fixture.

Build backend_window and frontend/dist first. Run in a desktop session with
ports 5173 and 9238 free. Uses the example's separate application identifier.
"""

import base64
import ctypes
import itertools
import json
import subprocess
import sys
import time
import unittest
from ctypes import wintypes

import httpx
import native_acceptance as native
import win32api
import win32con
import win32gui
import win32process
from websockets.sync.client import connect

USER32 = ctypes.WinDLL("user32", use_last_error=True)
USER32.SetProcessDPIAware()
USER32.GetMenuStringW.argtypes = [
  wintypes.HMENU,
  wintypes.UINT,
  wintypes.LPWSTR,
  ctypes.c_int,
  wintypes.UINT,
]
USER32.GetMenuStringW.restype = ctypes.c_int
USER32.GetMenuItemRect.argtypes = [
  wintypes.HWND,
  wintypes.HMENU,
  wintypes.UINT,
  ctypes.POINTER(wintypes.RECT),
]
USER32.GetMenuItemRect.restype = wintypes.BOOL

REPO = native.REPO
WINDOW = REPO / "frontend/src-tauri/target/debug/examples/backend_window.exe"


def wait_until(probe, timeout=30):
  deadline = time.monotonic() + timeout
  while time.monotonic() < deadline:
    result = probe()
    if result:
      return result
    time.sleep(0.05)
  raise AssertionError(f"condition did not become true: {probe}")


class WindowAcceptance(unittest.TestCase):
  artifact_root = REPO / ".scratch/windows-backend-lifecycle/tray-acceptance"

  @classmethod
  def setUpClass(cls):
    cls.server = subprocess.Popen(
      [
        sys._base_executable,
        "-m",
        "http.server",
        "5173",
        "--bind",
        "127.0.0.1",
        "--directory",
        str(REPO / "frontend/dist"),
      ],
      stdout=subprocess.DEVNULL,
      stderr=subprocess.DEVNULL,
      creationflags=subprocess.CREATE_NO_WINDOW,
    )

    def stop_server():
      if cls.server.poll() is None:
        cls.server.kill()
      cls.server.wait(timeout=10)

    cls.addClassCleanup(stop_server)
    with httpx.Client(trust_env=False) as client:

      def reachable():
        assert cls.server.poll() is None, "port 5173 is occupied"
        try:
          return client.get("http://127.0.0.1:5173").status_code == 200
        except httpx.HTTPError:
          return False

      wait_until(reachable)

  def setUp(self):
    self.fixture = native.NativeAcceptance()
    self.fixture.setUp()
    self.addCleanup(self.fixture.doCleanups)
    self.root = self.fixture.root
    (self.root / "allow-observation").touch()
    self.fixture.config["backend"]["startup_timeout_seconds"] = 60
    self.fixture.write_config()
    self.hosts = []
    self.launch_numbers = itertools.count()
    self.artifacts = self.artifact_root / self._testMethodName
    self.artifacts.mkdir(parents=True, exist_ok=True)
    self.ws = None
    self.sequence = 0
    self.addCleanup(self.stop_hosts)
    self.client = httpx.Client(trust_env=False, timeout=1)
    self.addCleanup(self.client.close)
    # Count real Python entry invocations, including attempts rejected by data
    # ownership. A database lock must not conceal duplicate backend creation.
    entry = self.root / "app/desktop.py"
    entry.write_text(
      "import os, pathlib\n"
      "pathlib.Path('python-starts').mkdir(exist_ok=True)\n"
      "pathlib.Path('python-starts', str(os.getpid())).touch()\n"
      + entry.read_text(encoding="utf-8"),
      encoding="utf-8",
    )

  def stop_hosts(self):
    if self.ws is not None:
      self.ws.close()
    for host in self.hosts:
      if host.poll() is None:
        host.kill()
      host.wait(timeout=10)
    # Kill-on-close reclaims owned Python and WebView teardown releases files.
    time.sleep(0.5)

  def launch(self):
    log = (self.artifacts / f"host-{next(self.launch_numbers)}.log").open("wb")
    self.addCleanup(log.close)
    host = subprocess.Popen(
      [str(WINDOW), str(self.root)],
      cwd=REPO.parent,
      env=dict(
        self.fixture.env,
        WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS="--remote-debugging-port=9238",
        WEBVIEW2_USER_DATA_FOLDER=str(self.root / "webview"),
      ),
      stdout=log,
      stderr=log,
    )
    self.hosts.append(host)
    return host

  def connect(self):
    def endpoint():
      try:
        targets = self.client.get("http://127.0.0.1:9238/json/list").json()
        return next(
          (t["webSocketDebuggerUrl"] for t in targets if t.get("type") == "page"), None
        )
      except (httpx.HTTPError, ValueError):
        return None

    self.ws = connect(wait_until(endpoint), proxy=None)
    wait_until(lambda: self.evaluate("Boolean(window.__TAURI_INTERNALS__)"))

  def call(self, method, **params):
    self.sequence += 1
    self.ws.send(
      json.dumps(
        dict(
          id=self.sequence,
          method=method,
          params=params,
        )
      )
    )
    while True:
      reply = json.loads(self.ws.recv(timeout=10))
      if reply.get("id") == self.sequence:
        self.assertNotIn("error", reply)
        self.assertNotIn("exceptionDetails", reply["result"])
        return reply["result"]

  def evaluate(self, expression):
    return (
      self.call(
        "Runtime.evaluate", expression=expression, returnByValue=True, awaitPromise=True
      )
      .get("result", {})
      .get("value")
    )

  def record(self, **fields):
    (self.artifacts / "result.json").write_text(
      json.dumps(dict(counts=self.counts(), **fields), ensure_ascii=False, indent=2),
      encoding="utf-8",
    )

  def screenshot(self):
    data = self.call("Page.captureScreenshot", format="png")["data"]
    (self.artifacts / "window.png").write_bytes(base64.b64decode(data))

  def snapshot(self):
    return self.evaluate("window.__TAURI_INTERNALS__.invoke('get_backend_state')")

  def state(self, expected):
    seen = []

    def matching():
      snapshot = self.snapshot()
      if not seen or snapshot != seen[-1]:
        seen.append(snapshot)
      return snapshot if snapshot["state"] == expected else None

    try:
      return wait_until(matching)
    except AssertionError as error:
      raise AssertionError(f"expected {expected}, saw {seen}") from error

  def window(self, host):
    windows = []

    def collect(hwnd, _):
      if (
        win32process.GetWindowThreadProcessId(hwnd)[1] == host.pid
        and win32gui.GetClassName(hwnd) == "Tauri Window"
      ):
        windows.append(hwnd)

    win32gui.EnumWindows(collect, None)
    self.assertEqual(len(windows), 1, windows)
    return windows[0]

  def counts(self):
    return tuple(
      len(list((self.root / name).glob("*")))
      for name in ("host-starts", "python-starts")
    )

  def tray_window(self, host):
    windows = []

    def collect(hwnd, _):
      if (
        win32process.GetWindowThreadProcessId(hwnd)[1] == host.pid
        and win32gui.GetClassName(hwnd) == "tray_icon_app"
      ):
        windows.append(hwnd)

    win32gui.EnumWindows(collect, None)
    self.assertEqual(len(windows), 1, windows)
    return windows[0]

  def tray_click(self, host, button):
    # Native shell notification boundary of tray-icon 0.24.2. No application
    # command or event-handler shortcut: exercise its actual Win32 dispatch.
    win32gui.PostMessage(self.tray_window(host), 6002, 0, button)

  def tray_menu(self, host, label, *, native_command=False):
    self.tray_click(host, win32con.WM_RBUTTONUP)

    def popup():
      menus = []

      def collect(hwnd, _):
        if (
          win32process.GetWindowThreadProcessId(hwnd)[1] == host.pid
          and win32gui.GetClassName(hwnd) == "#32768"
          and win32gui.IsWindowVisible(hwnd)
        ):
          menus.append(hwnd)

      win32gui.EnumWindows(collect, None)
      return menus[0] if menus else None

    hwnd = wait_until(popup)
    menu = win32gui.SendMessage(hwnd, 0x01E1, 0, 0)  # MN_GETHMENU
    labels = []
    for i in range(win32gui.GetMenuItemCount(menu)):
      text = ctypes.create_unicode_buffer(256)
      self.assertGreater(
        USER32.GetMenuStringW(menu, i, text, len(text), win32con.MF_BYPOSITION), 0
      )
      labels.append(text.value)
    self.assertEqual(labels, ["打开主窗口", "退出应用"])
    if native_command:
      # TrackPopupMenu 的选择向 tray-icon 宿主发送 WM_COMMAND，Muda 按菜单 ID
      # 分发真实菜单事件。锁屏时仅用于退出清理，不代表物理鼠标／键盘验收。
      owner = self.tray_window(host)
      index = labels.index(label)
      item_id = win32gui.GetMenuItemID(menu, index)
      self.assertGreater(item_id, 0)
      self.assertLessEqual(item_id, 0xFFFF)
      self.assertFalse(
        win32gui.GetMenuState(menu, index, win32con.MF_BYPOSITION)
        & (win32con.MF_DISABLED | win32con.MF_GRAYED)
      )
      win32gui.PostMessage(owner, win32con.WM_CANCELMODE, 0, 0)
      wait_until(
        lambda: not win32gui.IsWindow(hwnd) or not win32gui.IsWindowVisible(hwnd),
        timeout=5,
      )
      win32gui.PostMessage(owner, win32con.WM_COMMAND, item_id, 0)
      return
    rect = wintypes.RECT()
    self.assertTrue(
      USER32.GetMenuItemRect(0, menu, labels.index(label), ctypes.byref(rect))
    )
    left, top, right, bottom = rect.left, rect.top, rect.right, rect.bottom
    # Repeated menus can reopen directly beneath the unchanged cursor. Move
    # within the item first so Windows delivers a fresh hover notification.
    win32api.SetCursorPos((left + 2, top + 2))
    time.sleep(0.05)
    win32api.SetCursorPos(((left + right) // 2, (top + bottom) // 2))
    time.sleep(0.1)  # Let the native popup process the pointer move before click.
    self.assertEqual(
      win32gui.WindowFromPoint(win32api.GetCursorPos()),
      hwnd,
      "native menu is not under the pointer",
    )
    wait_until(
      lambda: (
        win32gui.GetMenuState(menu, labels.index(label), win32con.MF_BYPOSITION)
        & win32con.MF_HILITE
      ),
      timeout=5,
    )
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0)
    time.sleep(0.05)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0)
    wait_until(
      lambda: not win32gui.IsWindow(hwnd) or not win32gui.IsWindowVisible(hwnd),
      timeout=5,
    )

  def quit(self, host):
    # 保留真实菜单身份及正常退出断言；物理输入另由默认路径在解锁后验收。
    self.tray_menu(host, "退出应用", native_command=True)

  def reopen(self, first):
    window = self.window(first)
    win32gui.ShowWindow(window, win32con.SW_MINIMIZE)
    win32gui.ShowWindow(window, win32con.SW_HIDE)
    self.assertFalse(win32gui.IsWindowVisible(window))
    second = self.launch()
    # The secondary must leave before any plan load or Python spawn of its own.
    self.assertEqual(second.wait(timeout=10), 0)
    wait_until(
      lambda: (
        win32gui.IsWindowVisible(window)
        and not win32gui.IsIconic(window)
        and win32gui.GetForegroundWindow() == window
      )
    )
    return second
