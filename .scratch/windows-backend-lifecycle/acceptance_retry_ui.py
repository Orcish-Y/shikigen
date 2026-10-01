"""Real Tauri retry command/button, native ownership failure and manual recovery."""

import base64
import json
import subprocess
import sys
import time
from pathlib import Path

import httpx
import win32con
import win32event
import win32gui
import win32process
from websockets.sync.client import connect

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "frontend/src-tauri/tests"))
from native_acceptance import NativeAcceptance  # noqa: E402

ARTIFACTS = ROOT / ".scratch/windows-backend-lifecycle/retry-ui-acceptance"
ARTIFACTS.mkdir(exist_ok=True)
case = NativeAcceptance()
case.setUp()
host = None
server = None
ws = None
results = []
sequence = 0


def record(check, **fields):
  results.append(dict(check=check, **fields))
  print(json.dumps(results[-1], ensure_ascii=True), flush=True)
  (ARTIFACTS / "results.json").write_text(
    json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
  )


def call(method, **params):
  global sequence
  sequence += 1
  ws.send(json.dumps(dict(id=sequence, method=method, params=params)))
  while True:
    reply = json.loads(ws.recv(timeout=10))
    if reply.get("id") == sequence:
      assert "error" not in reply, reply
      return reply["result"]


def evaluate(expression):
  result = call(
    "Runtime.evaluate", expression=expression, returnByValue=True, awaitPromise=True
  )
  assert "exceptionDetails" not in result, result
  return result.get("result", {}).get("value")


def wait_state(predicate):
  deadline = time.monotonic() + 35
  while time.monotonic() < deadline:
    assert host.poll() is None, host.returncode
    value = evaluate("""(async () => window.__TAURI_INTERNALS__ ? ({
      snapshot: await window.__TAURI_INTERNALS__.invoke('get_backend_state'),
      text: document.body.innerText,
      retryDisabled: document.querySelector('.backend-screen button')?.disabled
    }) : null)()""")
    if value and predicate(value):
      return value
    time.sleep(0.05)
  raise AssertionError(value)


def screenshot(name):
  data = call("Page.captureScreenshot", format="png")["data"]
  (ARTIFACTS / name).write_bytes(base64.b64decode(data))


def close_window():
  windows = []

  def collect(hwnd, _):
    if (
      win32process.GetWindowThreadProcessId(hwnd)[1] == host.pid
      and win32gui.GetClassName(hwnd) == "Tauri Window"
    ):
      windows.append(hwnd)

  win32gui.EnumWindows(collect, None)
  assert len(windows) == 1, windows
  win32gui.PostMessage(windows[0], win32con.WM_CLOSE, 0, 0)


try:
  # An independent runtime keeps the original database; the desktop must fail
  # ownership checks without disturbing it. All data lives in this fixture.
  external = case.host()
  external_ready = external.state("ready")
  external_handles = case.process_handles()
  with (
    (ARTIFACTS / "frontend.log").open("wb") as frontend_log,
    (ARTIFACTS / "host.log").open("wb") as host_log,
    httpx.Client(trust_env=False, timeout=2) as client,
  ):
    server = subprocess.Popen(
      [
        sys._base_executable,
        "-m",
        "http.server",
        "5173",
        "--bind",
        "127.0.0.1",
        "--directory",
        str(ROOT / "frontend/dist"),
      ],
      stdout=frontend_log,
      stderr=frontend_log,
      creationflags=subprocess.CREATE_NO_WINDOW,
    )
    for _ in range(50):
      assert server.poll() is None, "port 5173 occupied"
      try:
        if client.get("http://127.0.0.1:5173").status_code == 200:
          break
      except httpx.HTTPError:
        pass
      time.sleep(0.1)
    host = subprocess.Popen(
      [
        str(ROOT / "frontend/src-tauri/target/debug/examples/backend_window.exe"),
        str(case.root),
      ],
      cwd=ROOT.parent,
      stdout=host_log,
      stderr=host_log,
      env=dict(
        case.env,
        WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS="--remote-debugging-port=9237",
        WEBVIEW2_USER_DATA_FOLDER=str(case.root / "webview"),
      ),
    )
    for _ in range(100):
      assert host.poll() is None, f"native window exited: {host.returncode:#x}"
      try:
        targets = client.get("http://127.0.0.1:9237/json/list").json()
        target = next(t for t in targets if t.get("type") == "page")
        ws = connect(target["webSocketDebuggerUrl"], proxy=None)
        break
      except (httpx.HTTPError, ValueError, StopIteration, OSError):
        time.sleep(0.1)
    assert ws is not None
    failed = wait_state(
      lambda s: s["snapshot"]["state"] == "failed" and s.get("retryDisabled") is True
    )
    assert failed["snapshot"]["error"]["code"] == "reclamation_unconfirmed"
    assert "in use" in failed["snapshot"]["error"]["message"].lower()
    denied = evaluate("window.__TAURI_INTERNALS__.invoke('retry_backend')")
    assert not denied["accepted"] and denied["reason"]
    assert denied["snapshot"]["startup_id"] == failed["snapshot"]["startup_id"]
    screenshot("01-unconfirmed-retry-disabled.png")
    record(
      "unconfirmed_reclamation_disables_button_and_rejects_command",
      snapshot=failed["snapshot"],
      reason=denied["reason"],
    )
    (case.root / "allow-observation").touch()
    confirmed = wait_state(
      lambda s: s["snapshot"]["can_retry"] and s.get("retryDisabled") is False
    )
    assert confirmed["snapshot"]["state"] == "failed"
    assert confirmed["snapshot"]["error"]["code"] == "RuntimeDataInUse", confirmed
    assert confirmed["snapshot"]["base_url"] is None
    screenshot("02-confirmed-manual-retry.png")
    record(
      "late_confirmation_restores_original_fault_and_enables_retry",
      snapshot=confirmed["snapshot"],
    )
    # Correct the actual project configuration without rebuilding/reopening Tauri.
    case.config["database"]["path"] = str(case.root / "recovered-chat.db")
    case.config["backend"]["port"] = 45320
    case.write_config()
    # Exercise the rendered button, followed by competing public IPC commands.
    replies = evaluate("""(async () => {
      document.querySelector('.backend-screen button').click();
      return await Promise.all(Array.from({length:16},
        () => window.__TAURI_INTERNALS__.invoke('retry_backend')));
    })()""")
    assert sum(r["accepted"] for r in replies) <= 1, replies
    ready = wait_state(
      lambda s: s["snapshot"]["state"] == "ready" and "后端已就绪" in s["text"]
    )
    assert ready["snapshot"]["startup_id"] != confirmed["snapshot"]["startup_id"]
    assert ready["snapshot"]["revision"] > confirmed["snapshot"]["revision"]
    assert ready["snapshot"]["base_url"] == "http://127.0.0.1:45320"
    ids = {r["snapshot"]["startup_id"] for r in replies}
    assert ids == {ready["snapshot"]["startup_id"]}, replies
    handles = case.process_handles()
    health = client.get(ready["snapshot"]["base_url"] + "/health/ready").json()
    assert health["startup_id"] == ready["snapshot"]["startup_id"]
    assert client.get(ready["snapshot"]["base_url"] + "/api/threads").json() == []
    assert external.process.poll() is None
    assert all(
      win32event.WaitForSingleObject(h, 0) == win32con.WAIT_TIMEOUT
      for h in external_handles
    )
    screenshot("03-recovered-ready.png")
    record(
      "config_fixed_button_retry_recovers_once_with_new_identity",
      host_pid=host.pid,
      snapshot=ready["snapshot"],
      concurrent_replies=len(replies),
      threads=[],
    )
    call("Page.reload")
    refreshed = wait_state(
      lambda s: s["snapshot"]["state"] == "ready" and "后端已就绪" in s["text"]
    )
    assert refreshed["snapshot"] == ready["snapshot"]
    record("page_refresh_keeps_the_same_backend", passed=True)
    close_window()
    host.wait(timeout=10)
    assert host.returncode == 0
    case.assert_reclaimed(handles, 45320)
    assert client.get(external_ready["base_url"] + "/health/ready").status_code == 200
    record(
      "quit_reclaims_retried_process_port_and_data_without_harming_independent_runtime",
      passed=True,
    )
finally:
  if ws is not None:
    ws.close()
  for process in (host, server):
    if process is not None and process.poll() is None:
      process.kill()
      process.wait(timeout=10)
  time.sleep(0.5)
  case.doCleanups()
