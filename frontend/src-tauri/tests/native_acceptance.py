"""Real Windows host-kill, descendant, ownership and path acceptance.

Run after cargo build --example backend_host. No model/network services used.
"""

import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

import httpx
import win32api
import win32con
import win32event

REPO = Path(__file__).resolve().parents[3]
HOST = REPO / "frontend/src-tauri/target/debug/examples/backend_host.exe"


class Host:
  def __init__(self, root, env):
    self.process = subprocess.Popen(
      [str(HOST), str(root)],
      cwd=root.parent,
      env=env,
      stdin=subprocess.PIPE,
      stdout=subprocess.PIPE,
      stderr=subprocess.PIPE,
      text=True,
      encoding="utf-8",
    )
    self.states = queue.Queue()

    def read():
      for line in self.process.stdout:
        self.states.put(json.loads(line))

    threading.Thread(target=read, daemon=True).start()

  def state(self, expected):
    deadline = time.monotonic() + 30
    seen = []
    while time.monotonic() < deadline:
      try:
        state = self.states.get(timeout=0.1)
      except queue.Empty:
        if self.process.poll() is not None:
          raise AssertionError(self.process.stderr.read()) from None
        continue
      seen.append(state)
      if state["state"] == expected:
        return state
      if state["state"] == "failed" and expected != "failed":
        raise AssertionError(state)
    raise AssertionError(seen)

  def close(self):
    if self.process.poll() is None:
      self.process.stdin.write("shutdown\n")
      self.process.stdin.flush()
      try:
        self.process.wait(timeout=15)
      except subprocess.TimeoutExpired:
        self.process.kill()
        self.process.wait(timeout=10)
    for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
      stream.close()


class NativeAcceptance(unittest.TestCase):
  def setUp(self):
    self.temp = tempfile.TemporaryDirectory(prefix="shikigen native acceptance ")
    self.addCleanup(self.temp.cleanup)
    self.root = Path(self.temp.name) / "project with spaces"
    self.root.mkdir()
    (self.root / "pyproject.toml").write_text(
      '[project]\nname="fixture"\nversion="0.0.0"'
    )
    venv = self.root / ".venv"
    (venv / "Scripts").mkdir(parents=True)
    shutil.copy(REPO / ".venv/Scripts/python.exe", venv / "Scripts/python.exe")
    shutil.copy(REPO / ".venv/pyvenv.cfg", venv / "pyvenv.cfg")
    app = self.root / "app"
    app.mkdir()
    (app / "__init__.py").write_text(f"__path__.append({str(REPO / 'app')!r})\n")
    bootstrap = f"""
import json, os, pathlib, runpy, subprocess, sys, site
site.addsitedir({str(REPO / ".venv/Lib/site-packages")!r})
from unittest.mock import patch
from runtime_fixtures import deterministic_agent
async def agent(**kwargs):
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(120)"],
        stdin=subprocess.DEVNULL,
    )
    pathlib.Path("pids.json").write_text(json.dumps([os.getpid(), child.pid]))
    return await deterministic_agent(**kwargs)
with patch("shikigen.runtime.composition.create_lead_agent", new=agent):
    runpy.run_path({str(REPO / "app/desktop.py")!r}, run_name="__main__")
"""
    (app / "desktop.py").write_text(bootstrap, encoding="utf-8")
    self.config = {
      "model": {},
      "mcp": {},
      "database": {"path": str(self.root / "chat.db")},
      "checkpointer": {"type": "memory"},
      "backend": {
        "port": 45200,
        "startup_timeout_seconds": 20,
        "shutdown_timeout_seconds": 2,
      },
    }
    self.write_config()
    self.env = dict(
      os.environ,
      PYTHONPATH=os.pathsep.join(
        map(
          str,
          [REPO / "tests", REPO / "packages/harness", REPO / ".venv/Lib/site-packages"],
        )
      ),
    )

  def write_config(self):
    (self.root / "config.json").write_text(json.dumps(self.config), encoding="utf-8")

  def host(self):
    host = Host(self.root, self.env)
    self.addCleanup(host.close)
    return host

  def process_handles(self):
    pids = json.loads((self.root / "pids.json").read_text())
    handles = [
      win32api.OpenProcess(
        win32con.SYNCHRONIZE | win32con.PROCESS_TERMINATE, False, pid
      )
      for pid in pids
    ]
    for handle in handles:
      self.addCleanup(handle.Close)
    return handles

  def test_killing_only_host_reclaims_backend_and_tool_but_not_external_service(self):
    external = subprocess.Popen(
      [sys.executable, "-c", "import time; time.sleep(120)"], stdin=subprocess.DEVNULL
    )
    self.addCleanup(
      lambda: (external.kill(), external.wait()) if external.poll() is None else None
    )
    host = self.host()
    ready = host.state("ready")
    handles = self.process_handles()
    with httpx.Client(trust_env=False) as client:
      self.assertEqual(client.get(ready["base_url"] + "/health/ready").status_code, 200)
      self.assertEqual(client.get(ready["base_url"] + "/api/threads").status_code, 200)
    # Popen.kill uses TerminateProcess on ONLY the Rust host, never taskkill /T.
    host.process.kill()
    host.process.wait(timeout=10)
    for handle in handles:
      self.assertEqual(
        win32event.WaitForSingleObject(handle, 5000), win32con.WAIT_OBJECT_0
      )
    self.assertIsNone(external.poll())
    # A new actual runtime acquiring the same DB proves the lock was released.
    second = self.host()
    second.state("ready")
    second.close()

  def test_independent_entry_contention_reports_original_ownership_error(self):
    # Ordinary HTTP entry owns the runtime via FastAPI lifespan. It has no
    # desktop control channel or desktop EOF semantics.
    script = f"""
import asyncio, json, site, socket
site.addsitedir({str(REPO / ".venv/Lib/site-packages")!r})
from unittest.mock import patch
from runtime_fixtures import deterministic_agent
import uvicorn
from app.server import create_app
sock = socket.socket()
sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
sock.bind(("127.0.0.1", 0))
print(json.dumps({{"port": sock.getsockname()[1]}}), flush=True)
with patch("shikigen.runtime.composition.create_lead_agent", new=deterministic_agent):
    server = uvicorn.Server(uvicorn.Config(create_app(), log_level="error"))
    asyncio.run(server.serve(sockets=[sock]))
"""
    independent = subprocess.Popen(
      [str(self.root / ".venv/Scripts/python.exe"), "-c", script],
      cwd=self.root,
      env=self.env,
      stdin=subprocess.DEVNULL,
      stdout=subprocess.PIPE,
      stderr=subprocess.DEVNULL,
      text=True,
    )

    def close():
      if independent.poll() is None:
        independent.kill()
        independent.wait(timeout=10)
      independent.stdout.close()

    self.addCleanup(close)
    bound = json.loads(independent.stdout.readline())
    with httpx.Client(trust_env=False) as client:
      deadline = time.monotonic() + 20
      while True:
        try:
          if (
            client.get(f"http://127.0.0.1:{bound['port']}/api/threads").status_code
            == 200
          ):
            break
        except httpx.TransportError:
          pass
        self.assertLess(time.monotonic(), deadline)
        time.sleep(0.05)
    host = self.host()
    failed = host.state("failed")
    self.assertIsNone(failed["base_url"])
    self.assertFalse(failed["can_retry"])
    self.assertIn("in use", failed["error"]["message"].lower())
    self.assertIsNone(independent.poll())

  def test_killing_python_reclaims_the_remaining_tool(self):
    host = self.host()
    host.state("ready")
    parent, tool = self.process_handles()
    win32api.TerminateProcess(parent, 7)
    failed = host.state("failed")
    self.assertIsNone(failed["base_url"])
    self.assertEqual(win32event.WaitForSingleObject(tool, 5000), win32con.WAIT_OBJECT_0)


if __name__ == "__main__":
  unittest.main(verbosity=2)
