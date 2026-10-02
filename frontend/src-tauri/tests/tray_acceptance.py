"""Real Windows tray, close-to-hide and lifecycle notification acceptance."""

import json
import time
import unittest
from concurrent.futures import ThreadPoolExecutor

import httpx
import win32api
import win32con
import win32event
import win32gui
from window_acceptance import REPO, WindowAcceptance, wait_until


class TrayAcceptance(WindowAcceptance):
  artifact_root = REPO / ".scratch/windows-backend-lifecycle/tray-acceptance"

  def hide(self, window):
    win32gui.PostMessage(window, win32con.WM_CLOSE, 0, 0)
    wait_until(lambda: not win32gui.IsWindowVisible(window))

  def assert_restored(self, window):
    wait_until(
      lambda: (
        win32gui.IsWindowVisible(window)
        and not win32gui.IsIconic(window)
        and win32gui.GetForegroundWindow() == window
      )
    )

  def test_idle_close_keeps_same_backend_and_renderer(self):
    host = self.launch()
    self.connect()
    ready = self.state("ready")
    window = self.window(host)
    self.evaluate("window.acceptanceSession = 'resident-session'")
    win32gui.PostMessage(window, win32con.WM_CLOSE, 0, 0)
    wait_until(lambda: not win32gui.IsWindowVisible(window))
    self.assertIsNone(host.poll())
    self.assertEqual(self.snapshot(), ready)
    health = self.client.get(ready["base_url"] + "/health/ready").json()
    self.assertEqual(health["startup_id"], ready["startup_id"])
    self.tray_click(host, win32con.WM_LBUTTONUP)
    self.assert_restored(window)
    self.assertEqual(self.snapshot(), ready)
    self.hide(window)
    self.tray_menu(host, "打开主窗口")
    self.assert_restored(window)
    self.hide(window)
    self.reopen(host)
    self.assertEqual(self.evaluate("window.acceptanceSession"), "resident-session")
    self.assertEqual(self.counts(), (1, 1))
    self.record(snapshot=ready, left_click=True, menu_open=True, same_renderer=True)
    self.quit(host)
    self.assertEqual(host.wait(timeout=10), 0)

  def test_hidden_backend_failure_is_shown_once_until_next_attempt(self):
    host = self.launch()
    self.connect()
    ready = self.state("ready")
    window = self.window(host)
    parent, tool = self.fixture.process_handles()
    (self.root / "allow-observation").unlink()
    win32gui.PostMessage(window, win32con.WM_CLOSE, 0, 0)
    wait_until(lambda: not win32gui.IsWindowVisible(window))
    win32api.TerminateProcess(parent, 7)
    unconfirmed = self.state("failed")
    self.assertFalse(unconfirmed["can_retry"])
    self.assertEqual(unconfirmed["error"]["code"], "reclamation_unconfirmed")
    wait_until(lambda: win32gui.IsWindowVisible(window), timeout=5)
    win32gui.PostMessage(window, win32con.WM_CLOSE, 0, 0)
    wait_until(lambda: not win32gui.IsWindowVisible(window))
    (self.root / "allow-observation").touch()
    wait_until(lambda: self.snapshot()["can_retry"])
    self.assertFalse(win32gui.IsWindowVisible(window))
    self.reopen(host)
    self.assertEqual(self.snapshot()["startup_id"], ready["startup_id"])
    self.assertEqual(self.counts(), (1, 1))
    self.screenshot()
    denied = self.snapshot()
    # An explicit retry creates a new fault episode, which may notify again.
    reply = self.evaluate("window.__TAURI_INTERNALS__.invoke('retry_backend')")
    self.assertTrue(reply["accepted"])
    newer = self.state("ready")
    self.assertNotEqual(newer["startup_id"], ready["startup_id"])
    new_parent, _ = self.fixture.process_handles()
    self.hide(window)
    win32api.TerminateProcess(new_parent, 8)
    self.state("failed")
    self.assert_restored(window)
    self.assertEqual(win32event.WaitForSingleObject(tool, 5000), win32con.WAIT_OBJECT_0)
    self.record(
      first_failure=unconfirmed, reclaimed=denied, next_failure=self.snapshot()
    )
    self.quit(host)
    self.assertEqual(host.wait(timeout=10), 0)

  def test_missing_tray_keeps_window_and_explains_close_will_quit(self):
    (self.root / "missing-tray-icon").touch()
    host = self.launch()
    self.connect()
    ready = self.state("ready")
    window = self.window(host)
    self.assertTrue(win32gui.IsWindowVisible(window))
    error = self.evaluate("window.__TAURI_INTERNALS__.invoke('get_tray_error')")
    self.assertIn("缺少应用图标", error)
    wait_until(lambda: error in self.evaluate("document.body.innerText"), timeout=5)
    self.assertEqual(self.snapshot(), ready)
    self.screenshot()
    self.record(snapshot=ready, tray_error=error, close_exits=True)
    win32gui.PostMessage(window, win32con.WM_CLOSE, 0, 0)
    self.assertEqual(host.wait(timeout=10), 0)

  def test_hidden_initialization_completes_and_tray_restores_same_attempt(self):
    self.fixture.env["DESKTOP_TEST_PAUSE_INIT"] = "1"
    host = self.launch()
    self.connect()
    wait_until(lambda: (self.root / "initializing").exists())
    starting = self.state("starting")
    window = self.window(host)
    self.hide(window)
    self.assertEqual(self.snapshot(), starting)
    (self.root / "continue-init").touch()
    ready = self.state("ready")
    self.assertEqual(ready["startup_id"], starting["startup_id"])
    self.assertFalse(win32gui.IsWindowVisible(window))
    self.tray_click(host, win32con.WM_LBUTTONUP)
    self.assert_restored(window)
    self.assertEqual(self.counts(), (1, 1))
    self.record(starting=starting, ready=ready, initialized_while_hidden=True)
    self.quit(host)
    self.assertEqual(host.wait(timeout=10), 0)

  def run_hidden_task(self, failure):
    self.fixture.env["DESKTOP_TEST_RESIDENT_TASK"] = "1"
    if failure:
      self.fixture.env["DESKTOP_TEST_TASK_FAILURE"] = "1"
    host = self.launch()
    self.connect()
    ready = self.state("ready")
    window = self.window(host)
    base = ready["base_url"]
    thread_id = self.client.post(base + "/api/threads").json()["thread_id"]

    def stream():
      with httpx.Client(trust_env=False, timeout=30) as client:
        return client.post(
          base + f"/api/threads/{thread_id}/stream",
          json={"message": "continue in background"},
        )

    with ThreadPoolExecutor(max_workers=1) as pool:
      pending = pool.submit(stream)
      wait_until(lambda: (self.root / "executing").exists())
      self.assertFalse(pending.done())
      self.hide(window)
      (self.root / "continue-task").touch()
      response = pending.result(timeout=15)
    self.assertEqual(response.status_code, 200)
    events = [
      json.loads(line[6:])
      for line in response.text.splitlines()
      if line.startswith("data: ")
    ]
    self.assertEqual(events[-1]["status"], "error" if failure else "completed")
    messages = self.client.get(base + f"/api/threads/{thread_id}/messages").json()
    if not failure:
      self.assertIn("后台任务已完成", json.dumps(messages, ensure_ascii=False))
    time.sleep(0.3)  # Let any incorrectly queued lifecycle activation arrive.
    self.assertFalse(win32gui.IsWindowVisible(window))
    self.assertEqual(self.snapshot(), ready)
    self.assertEqual(self.counts(), (1, 1))
    self.record(snapshot=ready, events=events, messages=messages, stayed_hidden=True)
    self.quit(host)
    self.assertEqual(host.wait(timeout=10), 0)

  def test_agent_task_completes_and_persists_after_close(self):
    self.run_hidden_task(failure=False)

  def test_agent_task_failure_does_not_activate_window_or_fail_backend(self):
    self.run_hidden_task(failure=True)

  def test_tray_quit_during_initialization_retains_unconfirmed_error_then_exits(self):
    self.fixture.env["DESKTOP_TEST_SYNC_INIT"] = "1"
    (self.root / "allow-observation").unlink()
    host = self.launch()
    self.connect()
    wait_until(lambda: (self.root / "initializing").exists())
    starting = self.state("starting")
    window = self.window(host)
    handles = self.fixture.process_handles()
    self.hide(window)
    self.quit(host)
    self.state("stopping")
    second = self.launch()
    self.assertEqual(second.wait(timeout=10), 0)
    failed = self.state("failed")
    self.assertEqual(failed["startup_id"], starting["startup_id"])
    self.assertFalse(failed["can_retry"])
    self.assertEqual(failed["error"]["code"], "reclamation_unconfirmed")
    self.assertTrue(win32gui.IsWindowVisible(window))
    # X must keep the error reachable while explicit exit is unfinished.
    win32gui.PostMessage(window, win32con.WM_CLOSE, 0, 0)
    third = self.launch()
    self.assertEqual(third.wait(timeout=10), 0)
    self.assertTrue(win32gui.IsWindowVisible(window))
    self.assertEqual(self.snapshot(), failed)
    self.assertEqual(self.counts(), (1, 1))
    reply = self.evaluate("window.__TAURI_INTERNALS__.invoke('retry_backend')")
    self.assertFalse(reply["accepted"])
    self.assertIn("退出", reply["reason"])
    self.screenshot()
    (self.root / "allow-observation").touch()
    self.assertEqual(host.wait(timeout=10), 0)
    for handle in handles:
      self.assertEqual(
        win32event.WaitForSingleObject(handle, 5000), win32con.WAIT_OBJECT_0
      )
    self.record(snapshot=failed, continued_exit=True, processes_reclaimed=True)

  def test_tray_quit_during_task_and_sse_cleans_up_owned_processes(self):
    self.fixture.env["DESKTOP_TEST_EXECUTING"] = "1"
    self.fixture.env["DESKTOP_TEST_STUCK_CLEANUP"] = "1"
    self.fixture.config["backend"]["shutdown_timeout_seconds"] = 1
    self.fixture.write_config()
    host = self.launch()
    self.connect()
    ready = self.state("ready")
    handles = self.fixture.process_handles()
    base = ready["base_url"]
    thread_id = self.client.post(base + "/api/threads").json()["thread_id"]
    with self.client.stream(
      "POST", base + f"/api/threads/{thread_id}/stream", json={"message": "wait"}
    ) as response:
      self.assertEqual(response.status_code, 200)
      wait_until(lambda: (self.root / "executing").exists())
      self.hide(self.window(host))
      started = time.monotonic()
      self.quit(host)
      wait_until(lambda: (self.root / "cleaning").exists())
      self.assertEqual(host.wait(timeout=10), 0)
    elapsed = time.monotonic() - started
    self.assertLess(elapsed, 8)
    for handle in handles:
      self.assertEqual(
        win32event.WaitForSingleObject(handle, 5000), win32con.WAIT_OBJECT_0
      )
    self.record(snapshot=ready, elapsed=elapsed, processes_reclaimed=True)


if __name__ == "__main__":
  unittest.main(verbosity=2)
