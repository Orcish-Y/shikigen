"""Real pipe/HTTP peer for the public Rust manager boundary tests."""

import argparse
import http.server
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--config")
parser.add_argument("--startup-id")
parser.add_argument("--port", type=int)
args = parser.parse_args()
mode = os.environ.get("BACKEND_TEST_MODE", "ready")

if mode == "startup_error":
  print(
    json.dumps(
      dict(
        version=1,
        startup_id=args.startup_id,
        type="startup_error",
        code="RuntimeDataInUseError",
        message="Runtime data is already in use",
      )
    ),
    flush=True,
  )
  time.sleep(60)
if mode == "oversize":
  sys.stdout.write("x" * 65537)
  sys.stdout.flush()
  time.sleep(60)
if mode == "timeout":
  time.sleep(60)


class Handler(http.server.BaseHTTPRequestHandler):
  def do_GET(self):
    if mode == "late_ready":
      Path(os.environ["BACKEND_TEST_PROBE_STARTED"]).touch()
      time.sleep(0.7)
    if mode == "slow_health":
      time.sleep(3)
    if mode == "unready":
      self.send_response(503)
      self.end_headers()
      return
    self.send_response(200)
    self.end_headers()
    if mode == "slow_body":
      time.sleep(3)
    result = dict(version=1, startup_id=args.startup_id, status="ready")
    if mode == "wrong_identity":
      result["startup_id"] = "another-startup"
    if mode == "wrong_version":
      result["version"] = True
    self.wfile.write(json.dumps(result).encode())

  def log_message(self, *_):
    pass


server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
if mode == "old_message":
  print(
    json.dumps(
      dict(
        version=99,
        startup_id=os.environ.get("BACKEND_TEST_OLD_ID", "old"),
        type="unknown",
      )
    ),
    flush=True,
  )
print(
  json.dumps(
    dict(version=1, startup_id=args.startup_id, type="bound", port=server.server_port)
  ),
  flush=True,
)
if mode == "stderr_flood":
  sys.stderr.buffer.write(b"log" * 1000000)
  sys.stderr.flush()
threading.Thread(target=server.serve_forever, daemon=True).start()
if mode == "old_flood_exit":
  subprocess.Popen(
    [
      sys.executable,
      "-c",
      "import json; line=json.dumps(dict(startup_id='old'));\n"
      "while True: print(line,flush=True)",
    ],
    stdin=subprocess.DEVNULL,
  )
if mode in ("exit_after_ready", "old_flood_exit"):
  time.sleep(1)
  sys.exit(7)
for line in sys.stdin:
  if json.loads(line)["type"] == "shutdown":
    if mode == "late_ready":
      time.sleep(60)
    break
server.server_close()
