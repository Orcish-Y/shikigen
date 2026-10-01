"""Real Tauri CloseRequested + recoverable platform observation fault acceptance."""

import base64
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
import win32con
import win32gui
import win32process
from websockets.sync.client import connect

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "frontend/src-tauri/tests"))
from native_acceptance import NativeAcceptance

ARTIFACTS = ROOT / ".scratch/windows-backend-lifecycle/shutdown-ui-acceptance"
ARTIFACTS.mkdir(exist_ok=True)
case = NativeAcceptance()
case.setUp()
process = None
server = None
ws = None
results = []


def record(check, **fields):
  results.append(dict(check=check, **fields))
  print(json.dumps(results[-1], ensure_ascii=True), flush=True)
  (ARTIFACTS / "results.json").write_text(
    json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
  )


def windows():
  found = []

  def collect(hwnd, _):
    if (
      win32process.GetWindowThreadProcessId(hwnd)[1] == process.pid
      and win32gui.GetClassName(hwnd) == "Tauri Window"
      and win32gui.IsWindowVisible(hwnd)
    ):
      found.append(hwnd)

  win32gui.EnumWindows(collect, None)
  return found


seq = 0


def call(method, **params):
  global seq
  seq += 1
  ws.send(json.dumps(dict(id=seq, method=method, params=params)))
  while True:
    reply = json.loads(ws.recv(timeout=10))
    if reply.get("id") == seq:
      assert "error" not in reply, reply
      return reply["result"]


def wait_state(expected):
  deadline = time.monotonic() + 30
  while time.monotonic() < deadline:
    value = call(
      "Runtime.evaluate",
      expression="""(async () => ({snapshot: await window.__TAURI_INTERNALS__.invoke('get_backend_state'), text: document.body.innerText}))()""",
      returnByValue=True,
      awaitPromise=True,
    )
    state = value.get("result", {}).get("value")
    if state and state["snapshot"]["state"] == expected:
      if expected != "failed" or "无法确认后端已完全退出" in state["text"]:
        return state
    time.sleep(0.05)
  raise AssertionError(value)


try:
  with (ARTIFACTS / "frontend.log").open("wb") as server_log, (
    ARTIFACTS / "host.log"
  ).open("wb") as host_log, httpx.Client(trust_env=False, timeout=2) as client:
    server = subprocess.Popen(
      [sys._base_executable, "-m", "http.server", "5173", "--bind", "127.0.0.1", "--directory", str(ROOT / "frontend/dist")],
      stdout=server_log, stderr=server_log, creationflags=subprocess.CREATE_NO_WINDOW,
    )
    for _ in range(50):
      assert server.poll() is None, "port 5173 is already occupied"
      try:
        if client.get("http://127.0.0.1:5173").status_code == 200:
          break
      except httpx.HTTPError:
        pass
      time.sleep(0.1)
    process = subprocess.Popen(
      [str(ROOT / "frontend/src-tauri/target/debug/examples/backend_window.exe"), str(case.root)],
      cwd=ROOT.parent, stdout=host_log, stderr=host_log,
      env=dict(case.env, WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS="--remote-debugging-port=9236", WEBVIEW2_USER_DATA_FOLDER=str(case.root / "webview")),
    )
    for _ in range(200):
      assert process.poll() is None, f"native window exited: {process.returncode:#x}"
      try:
        targets = client.get("http://127.0.0.1:9236/json/list").json()
        page = next(t for t in targets if t.get("type") == "page")
        ws = connect(page["webSocketDebuggerUrl"], proxy=None)
        break
      except (httpx.HTTPError, ValueError, StopIteration, OSError):
        time.sleep(0.1)
    assert ws is not None
    ready = wait_state("ready")
    handles = case.process_handles()
    before = windows()
    assert before
    win32gui.PostMessage(before[0], win32con.WM_CLOSE, 0, 0)
    failed = wait_state("failed")
    assert failed["snapshot"]["error"]["code"] == "reclamation_unconfirmed"
    assert failed["snapshot"]["base_url"] is None
    assert not failed["snapshot"]["can_retry"]
    assert "正在继续确认退出状态" in failed["text"]
    assert "关闭并重新打开" not in failed["text"]
    assert windows() == before and process.poll() is None
    screenshot = call("Page.captureScreenshot", format="png")
    (ARTIFACTS / "01-unconfirmed-window.png").write_bytes(base64.b64decode(screenshot["data"]))
    record("unconfirmed_keeps_error_window", host_pid=process.pid, snapshot=failed["snapshot"], text=failed["text"])
    # Repeated close must neither destroy the window nor cancel observation.
    win32gui.PostMessage(before[0], win32con.WM_CLOSE, 0, 0)
    time.sleep(0.5)
    assert windows() == before and process.poll() is None
    record("repeated_close_keeps_window", passed=True)
    (case.root / "allow-observation").touch()
    process.wait(timeout=5)
    assert process.returncode == 0
    case.assert_reclaimed(handles, int(ready["snapshot"]["base_url"].rsplit(":", 1)[1]))
    record("later_confirmation_exits_and_releases_process_port_and_data", passed=True)
finally:
  if ws is not None:
    ws.close()
  for child in (process, server):
    if child is not None and child.poll() is None:
      child.kill()
      child.wait(timeout=10)
  # TemporaryDirectory belongs only to this fixture and contains its isolated DBs.
  time.sleep(0.5)
  case.doCleanups()
