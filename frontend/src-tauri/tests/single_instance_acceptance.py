"""Real Windows single-instance, window activation and backend ownership checks.

Build backend_window and frontend/dist first. Run in a desktop session with
ports 5173 and 9238 free. Uses the example's separate application identifier.
"""

import base64
import itertools
import json
import subprocess
import sys
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor

import httpx
import native_acceptance as native
import win32con
import win32event
import win32gui
import win32process
from websockets.sync.client import connect

REPO = native.REPO
WINDOW = REPO / "frontend/src-tauri/target/debug/examples/backend_window.exe"
ARTIFACTS = REPO / ".scratch/windows-backend-lifecycle/single-instance-acceptance"


def wait_until(probe, timeout=30):
  deadline = time.monotonic() + timeout
  while time.monotonic() < deadline:
    result = probe()
    if result:
      return result
    time.sleep(0.05)
  raise AssertionError(f"condition did not become true: {probe}")


class SingleInstanceAcceptance(unittest.TestCase):
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
    self.artifacts = ARTIFACTS / self._testMethodName
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
    def matching():
      snapshot = self.snapshot()
      return snapshot if snapshot["state"] == expected else None

    return wait_until(matching)

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

  def test_ready_reopen_restores_existing_window_and_session(self):
    first = self.launch()
    self.connect()
    before = self.state("ready")
    self.evaluate("window.acceptanceSession = 'same-renderer'")
    self.reopen(first)
    self.assertEqual(self.snapshot(), before)
    self.assertEqual(self.evaluate("window.acceptanceSession"), "same-renderer")
    self.assertEqual(self.counts(), (1, 1))
    health = self.client.get(before["base_url"] + "/health/ready").json()
    self.assertEqual(health["startup_id"], before["startup_id"])
    self.screenshot()
    self.record(snapshot=before, foreground_pid=first.pid, session_preserved=True)
    win32gui.PostMessage(self.window(first), win32con.WM_CLOSE, 0, 0)
    self.assertEqual(first.wait(timeout=10), 0)
    self.ws.close()
    self.ws = None
    successor = self.launch()
    self.connect()
    after = self.state("ready")
    self.assertNotEqual(after["startup_id"], before["startup_id"])
    self.assertEqual(self.counts(), (2, 2))
    self.record(
      snapshot=before,
      foreground_pid=first.pid,
      session_preserved=True,
      after_full_exit=after,
      successor_pid=successor.pid,
    )

  def test_starting_reopen_only_shows_current_initialization(self):
    self.fixture.env["DESKTOP_TEST_BLOCK_INIT"] = "1"
    first = self.launch()
    self.connect()
    wait_until(lambda: (self.root / "initializing").exists())
    before = self.state("starting")
    self.reopen(first)
    self.assertEqual(self.snapshot(), before)
    self.assertEqual(self.counts(), (1, 1))
    self.screenshot()
    self.record(snapshot=before, foreground_pid=first.pid)
    win32gui.PostMessage(self.window(first), win32con.WM_CLOSE, 0, 0)
    self.assertEqual(first.wait(timeout=10), 0)

  def test_failed_reopen_does_not_retry_even_after_configuration_is_fixed(self):
    self.fixture.config["backend"]["port"] = None
    self.fixture.write_config()
    first = self.launch()
    self.connect()
    before = self.state("failed")
    self.assertTrue(before["can_retry"])
    self.fixture.config["backend"]["port"] = 45200
    self.fixture.write_config()
    self.reopen(first)
    self.assertEqual(self.snapshot(), before)
    self.assertEqual(self.counts(), (1, 0))
    self.screenshot()
    self.record(snapshot=before, foreground_pid=first.pid, config_fixed=True)
    win32gui.PostMessage(self.window(first), win32con.WM_CLOSE, 0, 0)
    self.assertEqual(first.wait(timeout=10), 0)

  def test_reopen_during_quit_and_unconfirmed_reclamation_keeps_exiting(self):
    self.fixture.env["DESKTOP_TEST_SYNC_INIT"] = "1"
    (self.root / "allow-observation").unlink()
    first = self.launch()
    self.connect()
    wait_until(lambda: (self.root / "initializing").exists())
    before = self.state("starting")
    window = self.window(first)
    win32gui.PostMessage(window, win32con.WM_CLOSE, 0, 0)
    self.state("stopping")
    win32gui.ShowWindow(window, win32con.SW_HIDE)
    second = self.launch()
    self.assertEqual(second.wait(timeout=10), 0)
    unconfirmed = self.state("failed")
    self.assertEqual(unconfirmed["error"]["code"], "reclamation_unconfirmed")
    self.assertFalse(unconfirmed["can_retry"])
    self.assertEqual(unconfirmed["startup_id"], before["startup_id"])
    # Failed is also a possible *exit* state: a state-string check is inadequate.
    third = self.launch()
    self.assertEqual(third.wait(timeout=10), 0)
    time.sleep(0.3)  # Allow queued window activation to execute, if any.
    self.assertFalse(win32gui.IsWindowVisible(window))
    self.assertEqual(self.snapshot(), unconfirmed)
    self.assertEqual(self.counts(), (1, 1))
    denied = self.evaluate("window.__TAURI_INTERNALS__.invoke('retry_backend')")
    self.assertFalse(denied["accepted"])
    self.assertIn("退出", denied["reason"])
    (self.root / "allow-observation").touch()
    self.assertEqual(first.wait(timeout=10), 0)
    self.record(
      snapshot=unconfirmed, host_pid=first.pid, stayed_hidden=True, quit_completed=True
    )

  def test_simultaneous_launches_create_only_one_host_runtime(self):
    barrier = threading.Barrier(8)

    def launch_together(_):
      barrier.wait(timeout=10)
      return self.launch()

    with ThreadPoolExecutor(max_workers=8) as pool:
      hosts = list(pool.map(launch_together, range(8)))
    self.connect()
    ready = self.state("ready")
    wait_until(lambda: sum(p.poll() is None for p in hosts) == 1)
    owner = next(p for p in hosts if p.poll() is None)
    self.assertTrue(all(p is owner or p.returncode == 0 for p in hosts))
    self.assertEqual(self.counts(), (1, 1))
    self.assertTrue(win32gui.IsWindowVisible(self.window(owner)))
    health = self.client.get(ready["base_url"] + "/health/ready").json()
    self.assertEqual(health["startup_id"], ready["startup_id"])
    self.record(
      snapshot=ready,
      owner_pid=owner.pid,
      secondary_exit_codes=[p.returncode for p in hosts if p is not owner],
    )
    win32gui.PostMessage(self.window(owner), win32con.WM_CLOSE, 0, 0)
    self.assertEqual(owner.wait(timeout=10), 0)

  def test_departed_notification_owner_cannot_leave_a_second_unprotected_host(self):
    # Deterministically reproduce the Windows state at the plugin's exit race:
    # another process still holds its named mutex, but the IPC window is gone.
    # Real kernel mutex + real Tauri/plugin; no fake BackendManager or process.
    identifier = "dev.shikigen.desktop.acceptance"
    self.assertFalse(win32gui.FindWindow(identifier + "-sic", identifier + "-siw"))
    old_handle = win32event.CreateMutex(None, False, identifier + "-sim")
    try:
      orphaned = self.launch()
      self.assertEqual(orphaned.wait(timeout=10), 0)
      self.assertEqual(self.counts(), (0, 0))
    finally:
      old_handle.Close()
    owner = self.launch()
    self.connect()
    ready = self.state("ready")
    self.reopen(owner)
    self.assertEqual(self.snapshot(), ready)
    self.assertEqual(self.counts(), (1, 1))
    self.record(snapshot=ready, owner_pid=owner.pid, orphaned_exit=0)
    win32gui.PostMessage(self.window(owner), win32con.WM_CLOSE, 0, 0)
    self.assertEqual(owner.wait(timeout=10), 0)


if __name__ == "__main__":
  unittest.main(verbosity=2)
