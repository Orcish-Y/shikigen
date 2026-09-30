"""Ad hoc acceptance of the real Tauri window, via local WebView2 CDP."""
import base64
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import time

import httpx
import win32api
import win32con
import win32event
import win32gui
import win32process
from websockets.sync.client import connect

ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = ROOT / ".scratch/windows-backend-lifecycle/ui-acceptance"
ARTIFACTS.mkdir(exist_ok=True)
EXE = ROOT / "frontend/src-tauri/target/debug/shikigen-desktop.exe"
CLIENT = httpx.Client(trust_env=False, timeout=2)
RESULTS = []


def record(name, **fields):
    result = dict(check=name, **fields)
    RESULTS.append(result)
    print(json.dumps(result, ensure_ascii=True), flush=True)
    (ARTIFACTS / "results.json").write_text(
        json.dumps(RESULTS, ensure_ascii=False, indent=2), encoding="utf-8"
    )


class CDP:
    def __init__(self, port):
        self.port = port
        started = time.monotonic()
        while time.monotonic() - started < 20:
            try:
                targets = CLIENT.get(f"http://127.0.0.1:{port}/json/list").json()
                target = next(t for t in targets if t.get("type") == "page")
                self.ws = connect(target["webSocketDebuggerUrl"], proxy=None)
                self.seq = 0
                return
            except (httpx.HTTPError, ValueError, StopIteration, OSError):
                time.sleep(0.1)
        raise AssertionError("WebView2 debugger did not become available")

    def call(self, method, **params):
        self.seq += 1
        self.ws.send(json.dumps(dict(id=self.seq, method=method, params=params)))
        while True:
            result = json.loads(self.ws.recv(timeout=10))
            if result.get("id") == self.seq:
                if "error" in result:
                    raise AssertionError(result["error"])
                return result["result"]

    def evaluate(self, expression):
        result = self.call("Runtime.evaluate", expression=expression,
                           returnByValue=True, awaitPromise=True)
        if "exceptionDetails" in result:
            raise AssertionError(result["exceptionDetails"])
        return result["result"].get("value")

    def inspect(self):
        return self.evaluate("""(async () => ({
          snapshot: window.__TAURI_INTERNALS__
            ? await window.__TAURI_INTERNALS__.invoke('get_backend_state') : null,
          text: document.body.innerText,
          title: document.title,
          url: location.href
        }))()""")

    def wait(self, state):
        started = time.monotonic()
        first = None
        while time.monotonic() - started < 70:
            try:
                result = self.inspect()
                snapshot = result["snapshot"]
                if snapshot:
                    if first is None:
                        first = snapshot
                        record("first_snapshot", snapshot=snapshot)
                        if snapshot["state"] == "starting" and result["text"]:
                            self.screenshot("00-starting-" + str(self.port))
                    visible = (
                        state == "ready" and "后端已就绪" in result["text"]
                        or state == "failed" and "后端启动或运行失败" in result["text"]
                        or state not in ("ready", "failed")
                    )
                    if snapshot["state"] == state and visible:
                        return result
                    if snapshot["state"] == "failed" and state != "failed":
                        raise AssertionError(result)
            except AssertionError as error:
                if "TAURI_INTERNALS" not in str(error):
                    raise
            time.sleep(0.1)
        raise AssertionError(f"did not reach {state}")

    def screenshot(self, name):
        result = self.call("Page.captureScreenshot", format="png")
        (ARTIFACTS / f"{name}.png").write_bytes(base64.b64decode(result["data"]))

    def close(self):
        self.ws.close()


class Entry(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG),
                ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260)]


def python_descendants(pid):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
    kernel.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(Entry)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateToolhelp32Snapshot(2, 0)
    rows = []
    try:
        entry = Entry(dwSize=ctypes.sizeof(Entry))
        ok = kernel.Process32FirstW(handle, ctypes.byref(entry))
        while ok:
            rows.append((entry.th32ProcessID, entry.th32ParentProcessID, entry.szExeFile))
            ok = kernel.Process32NextW(handle, ctypes.byref(entry))
    finally:
        kernel.CloseHandle(handle)
    times = {}
    def creation(process_id):
        if process_id not in times:
            try:
                handle = win32api.OpenProcess(0x1000, False, process_id)
                try:
                    times[process_id] = win32process.GetProcessTimes(handle)["CreationTime"]
                finally:
                    handle.Close()
            except win32api.error:
                times[process_id] = None
        return times[process_id]
    owned = {pid}
    while True:
        found = {child for child, parent, _ in rows
                 if parent in owned and creation(child) is not None
                 and creation(parent) is not None
                 and creation(child) >= creation(parent)}
        if found.issubset(owned):
            break
        owned.update(found)
    return sorted(child for child, _, name in rows
                  if child in owned and name.lower() in ("python.exe", "pythonw.exe"))


def retained_handles(pids):
    return [win32api.OpenProcess(win32con.SYNCHRONIZE, False, pid) for pid in pids]


def assert_exited(handles):
    for handle in handles:
        assert win32event.WaitForSingleObject(handle, 5000) == win32con.WAIT_OBJECT_0
        handle.Close()


def close_window(process):
    windows = []
    def collect(hwnd, _):
        if (win32process.GetWindowThreadProcessId(hwnd)[1] == process.pid
                and win32gui.IsWindowVisible(hwnd)
                and win32gui.GetClassName(hwnd) == "Tauri Window"):
            windows.append(hwnd)
    win32gui.EnumWindows(collect, None)
    assert windows, "no visible Tauri window"
    record("close_window_sent", host_pid=process.pid,
           windows=[dict(hwnd=w, title=win32gui.GetWindowText(w),
                         class_name=win32gui.GetClassName(w)) for w in windows])
    for hwnd in windows:
        win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
    process.wait(timeout=20)


def launch(port, name):
    env = dict(os.environ)
    env["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = f"--remote-debugging-port={port}"
    env["WEBVIEW2_USER_DATA_FOLDER"] = str(ARTIFACTS / f"webview-{name}")
    log = (ARTIFACTS / f"{name}.log").open("wb")
    process = subprocess.Popen([str(EXE)], cwd=ROOT.parent, env=env,
                               stdout=log, stderr=log)
    HOSTS.append((process, log))
    return process, CDP(port)


HOSTS = []
server_log = (ARTIFACTS / "frontend-server.log").open("wb")
server = subprocess.Popen([str(ROOT / ".venv/Scripts/python.exe"), "-m", "http.server",
                           "5173", "--bind", "127.0.0.1", "--directory", str(ROOT / "frontend/dist")],
                          stdout=server_log, stderr=server_log,
                          creationflags=subprocess.CREATE_NO_WINDOW)
try:
    for _ in range(50):
        try:
            assert CLIENT.get("http://127.0.0.1:5173").status_code == 200
            break
        except httpx.HTTPError:
            time.sleep(0.1)
    else:
        raise AssertionError("frontend server did not start")

    primary, page = launch(9237, "primary")
    ready = page.wait("ready")
    assert "后端已就绪" in ready["text"], ready
    pids = python_descendants(primary.pid)
    assert pids, "no owned Python process"
    page.screenshot("01-ready")
    record("real_window_ready", host_pid=primary.pid, python_pids=pids,
           snapshot=ready["snapshot"], page_status="后端已就绪")
    status_labels = page.evaluate("""['.app-connection', '.connection-card', '.composer-status']
      .map(selector => document.querySelector(selector).innerText)""")
    assert all("后端已就绪" in label for label in status_labels), status_labels
    record("consistent_ready_labels", labels=status_labels)
    health = CLIENT.get(ready["snapshot"]["base_url"] + "/health/ready").json()
    assert health["startup_id"] == ready["snapshot"]["startup_id"]

    for _ in range(3):
        page.call("Page.reload", ignoreCache=True)
        refreshed = page.wait("ready")
        assert refreshed["snapshot"] == ready["snapshot"]
        assert python_descendants(primary.pid) == pids
        assert "后端已就绪" in refreshed["text"]
    page.screenshot("02-after-refresh")
    record("three_refreshes_keep_backend", startup_id=health["startup_id"],
           python_pids=pids, revision=ready["snapshot"]["revision"])

    second, failure_page = launch(9238, "contender")
    failed = failure_page.wait("failed")
    assert failed["snapshot"]["base_url"] is None
    assert failed["snapshot"]["can_retry"] is False
    assert "in use" in failed["text"].lower(), failed
    failure_page.screenshot("03-data-in-use")
    assert CLIENT.get(ready["snapshot"]["base_url"] + "/health/ready").json() == health
    record("real_failure_page", snapshot=failed["snapshot"], owner_still_ready=True)
    failure_page.close()
    close_window(second)
    record("failed_window_closes", exit_code=second.returncode)

    handles = retained_handles(pids)
    page.close()
    close_window(primary)
    assert_exited(handles)
    record("normal_window_close_reclaims_python", exit_code=primary.returncode,
           python_pids=pids)

    third, crash_page = launch(9239, "host-kill")
    reopened = crash_page.wait("ready")
    crash_page.screenshot("04-reopened")
    pids = python_descendants(third.pid)
    handles = retained_handles(pids)
    crash_page.close()
    third.kill()  # ONLY TerminateProcess(host), no tree traversal.
    third.wait(timeout=10)
    assert_exited(handles)
    assert CLIENT.get("http://127.0.0.1:5173").status_code == 200
    record("kill_only_real_tauri_host", host_pid=third.pid,
           python_pids=pids, independent_frontend_service_alive=True)
    record("acceptance_complete", passed=True)
finally:
    for process, log in reversed(HOSTS):
        if process.poll() is None:
            try:
                close_window(process)
            except Exception:
                process.kill()
                process.wait(timeout=10)
        log.close()
    server.terminate()
    server.wait(timeout=10)
    server_log.close()
    CLIENT.close()
