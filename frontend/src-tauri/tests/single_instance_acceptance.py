"""Real Windows single-instance, activation and backend ownership acceptance."""

import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor

import win32con
import win32event
import win32gui
from window_acceptance import REPO, WindowAcceptance, wait_until


class SingleInstanceAcceptance(WindowAcceptance):
  artifact_root = (
    REPO / ".scratch/windows-backend-lifecycle/tray-single-instance-acceptance"
  )

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
    self.quit(first)
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
    self.quit(first)
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
    self.quit(first)
    self.assertEqual(first.wait(timeout=10), 0)

  def test_reopen_during_quit_and_unconfirmed_reclamation_keeps_exiting(self):
    self.fixture.env["DESKTOP_TEST_SYNC_INIT"] = "1"
    (self.root / "allow-observation").unlink()
    first = self.launch()
    self.connect()
    wait_until(lambda: (self.root / "initializing").exists())
    before = self.state("starting")
    window = self.window(first)
    self.quit(first)
    # Native menu dismissal can finish after the short stopping phase.
    wait_until(lambda: self.snapshot()["state"] in {"stopping", "reclaiming", "failed"})
    win32gui.ShowWindow(window, win32con.SW_HIDE)
    second = self.launch()
    self.assertEqual(second.wait(timeout=10), 0)
    unconfirmed = self.state("failed")
    self.assertEqual(unconfirmed["error"]["code"], "reclamation_unconfirmed")
    self.assertFalse(unconfirmed["can_retry"])
    self.assertEqual(unconfirmed["startup_id"], before["startup_id"])
    # The external test hide can race the one-time fault notification. Check
    # only single-instance activation here; ticket 08 tests reveal through X.
    # Let any queued failure reveal settle before hiding for the next opener.
    time.sleep(0.3)
    win32gui.ShowWindow(window, win32con.SW_HIDE)
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
    self.quit(owner)
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
    self.quit(owner)
    self.assertEqual(owner.wait(timeout=10), 0)


if __name__ == "__main__":
  unittest.main(verbosity=2)
