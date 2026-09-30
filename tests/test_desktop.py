import asyncio
import json
import os
import socket
import sys
import tempfile
import unittest
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


class DesktopTests(unittest.IsolatedAsyncioTestCase):
  async def asyncSetUp(self):
    self.directory = tempfile.TemporaryDirectory(prefix="desktop test ")
    self.addCleanup(self.directory.cleanup)
    self.config = Path(self.directory.name) / "config.json"
    self.config.write_text(
      json.dumps(
        {
          "model": {},
          "mcp": {},
          "checkpointer": {"type": "memory"},
          "database": {"path": str(Path(self.directory.name) / "chat.db")},
        }
      ),
      encoding="utf-8",
    )

  async def launch(self, port=None, env=None):
    if port is None:
      with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    process = await asyncio.create_subprocess_exec(
      sys.executable,
      str(ROOT / "tests/desktop_process.py"),
      "--config",
      str(self.config),
      "--startup-id",
      "test-start",
      "--port",
      str(port),
      cwd=self.directory.name,
      stdin=asyncio.subprocess.PIPE,
      stdout=asyncio.subprocess.PIPE,
      stderr=asyncio.subprocess.PIPE,
      env={
        key: value
        for key, value in {**os.environ, **(env or {})}.items()
        if value is not None
      },
    )

    async def cleanup():
      if process.returncode is None:
        process.kill()
      await process.wait()

    self.addAsyncCleanup(cleanup)
    return process

  async def bound(self, process):
    line = await asyncio.wait_for(process.stdout.readline(), 30)
    if not line:
      self.fail((await process.stderr.read()).decode())
    message = json.loads(line)
    self.assertEqual(message["type"], "bound", message)
    self.assertEqual(message["version"], 1)
    self.assertEqual(message["startup_id"], "test-start")
    return message["port"]

  async def ready(self, port):
    async with httpx.AsyncClient(trust_env=False) as client:
      async with asyncio.timeout(30):
        while True:
          try:
            response = await client.get(
              f"http://127.0.0.1:{port}/health/ready", timeout=1
            )
            if response.status_code == 200:
              self.assertEqual(
                response.json(),
                {
                  "version": 1,
                  "startup_id": "test-start",
                  "status": "ready",
                },
              )
              return
          except httpx.TransportError:
            pass
          await asyncio.sleep(0.05)

  async def test_bound_ready_business_and_shutdown(self):
    process = await self.launch()
    port = await self.bound(process)
    await self.ready(port)
    with socket.socket() as contender:
      contender.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
      with self.assertRaises(OSError):
        contender.bind(("127.0.0.1", port))
    async with httpx.AsyncClient(trust_env=False) as client:
      response = await client.get(f"http://127.0.0.1:{port}/api/threads")
      self.assertEqual(response.status_code, 200)
      created = await client.post(f"http://127.0.0.1:{port}/api/threads")
      thread_id = created.json()["thread_id"]
      response = await client.post(
        f"http://127.0.0.1:{port}/api/threads/{thread_id}/stream",
        json={"message": "1 + 2"},
        timeout=10,
      )
      self.assertEqual(response.status_code, 200)
      self.assertIn('"status":"completed"', response.text)
    process.stdin.write(b'{"version":1,"startup_id":"test-start","type":"shutdown"}\n')
    await process.stdin.drain()
    stdout, stderr = await asyncio.wait_for(process.communicate(), 20)
    self.assertEqual(process.returncode, 0, stderr.decode())
    self.assertEqual(stdout, b"")
    self.assertIn(b"fixture ordinary stdout", stderr)
    self.assertIn(b"fixture child stdout", stderr)

  async def test_bind_errors_skip_10013_but_fail_other_errors(self):
    process = await self.launch(port=65490, env={"DESKTOP_TEST_BIND_ERROR": "10013"})
    self.assertGreaterEqual(await self.bound(process), 65491)
    process.stdin.close()
    _, stderr = await asyncio.wait_for(process.communicate(), 20)
    self.assertEqual(process.returncode, 0, stderr.decode())
    self.assertIn(b"10013", stderr)
    process = await self.launch(env={"DESKTOP_TEST_BIND_ERROR": "10049"})
    # 不关闭 stdin：启动失败本身必须能退出，不等待读取线程。
    await asyncio.wait_for(process.wait(), 20)
    message = json.loads(await process.stdout.readline())
    self.assertEqual(message["type"], "startup_error")
    self.assertIn("10049", message["message"])
    self.assertNotEqual(process.returncode, 0)

  async def test_contiguous_occupied_ports_and_exhaustion(self):
    sockets = []
    self.addCleanup(lambda: [sock.close() for sock in sockets])
    # 靠近端口上限选一段本机可用端口，并实际持有前两个。
    for start in range(65400, 65530, 3):
      try:
        for port in (start, start + 1):
          sock = socket.socket()
          sockets.append(sock)
          if sys.platform == "win32":
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
          sock.bind(("127.0.0.1", port))
        break
      except OSError:
        for sock in sockets:
          sock.close()
        sockets.clear()
    else:
      self.fail("No port pair available for test")
    process = await self.launch(port=start)
    actual = await self.bound(process)
    self.assertGreaterEqual(actual, start + 2)
    await self.ready(actual)
    process.stdin.close()
    await asyncio.wait_for(process.wait(), 20)
    process = await self.launch(port=65535, env={"DESKTOP_TEST_BIND_ERROR": "10048"})
    await asyncio.wait_for(process.wait(), 20)
    message = json.loads(await process.stdout.readline())
    self.assertEqual(message["type"], "startup_error")
    self.assertIn("65535", message["message"])

  async def test_environment_loaded_before_config_without_overriding_host(self):
    root = Path(self.directory.name)
    (root / ".env").write_text("DESKTOP_TEST_MODEL=dotenv-model\n", encoding="utf-8")
    config = json.loads(self.config.read_text(encoding="utf-8"))
    config["model"]["default"] = "$DESKTOP_TEST_MODEL"
    self.config.write_text(json.dumps(config), encoding="utf-8")
    for value in (None, "", "host-model"):
      # 空字符串同样是明确提供的宿主环境值，应保留并被配置校验拒绝。
      process = await self.launch(
        env={
          "DESKTOP_TEST_ENV_ROOT": str(root),
          "DESKTOP_TEST_MODEL": value,
        }
      )
      if value != "":
        await self.ready(await self.bound(process))
        process.stdin.close()
        await asyncio.wait_for(process.wait(), 20)
        self.assertEqual(process.returncode, 0)
      else:
        await asyncio.wait_for(process.wait(), 20)
        error = json.loads(await process.stdout.readline())
        self.assertEqual(error["type"], "startup_error")
        self.assertIn("model.default", error["message"])

  async def test_missing_environment_reports_name_and_exits(self):
    config = json.loads(self.config.read_text(encoding="utf-8"))
    config["model"]["default"] = "$DESKTOP_TICKET03_MISSING_VARIABLE"
    self.config.write_text(json.dumps(config), encoding="utf-8")
    process = await self.launch()
    await asyncio.wait_for(process.wait(), 20)
    error = json.loads(await process.stdout.readline())
    self.assertEqual(error["type"], "startup_error")
    self.assertIn("DESKTOP_TICKET03_MISSING_VARIABLE", error["message"])

  async def test_eof_closes_backend(self):
    process = await self.launch(env={"DESKTOP_TEST_ENV_ROOT": self.directory.name})
    await self.ready(await self.bound(process))
    process.stdin.close()
    stdout, stderr = await asyncio.wait_for(process.communicate(), 20)
    self.assertEqual(process.returncode, 0, stderr.decode())
    self.assertEqual(stdout, b"")

  async def test_message_size_boundary_and_partial_eof(self):
    message = b'{"version":1,"startup_id":"test-start","type":"shutdown"}'
    process = await self.launch()
    await self.ready(await self.bound(process))
    process.stdin.write(message + b" " * (65535 - len(message)) + b"\n")
    await process.stdin.drain()
    # 达到上限的合法消息也必须在输入仍打开时完成退出。
    await asyncio.wait_for(process.wait(), 20)
    self.assertEqual(process.returncode, 0, (await process.stderr.read()).decode())
    process = await self.launch()
    await self.ready(await self.bound(process))
    process.stdin.write(message)
    await process.stdin.drain()
    process.stdin.close()
    _, stderr = await asyncio.wait_for(process.communicate(), 20)
    self.assertNotEqual(process.returncode, 0)
    self.assertIn(b"lacks newline", stderr)

  async def test_protocol_errors_exit_without_waiting_for_eof(self):
    cases = [
      b"broken\n",
      b"\xff\n",
      b"[]\n",
      b"{}\n",
      b'{"startup_id":"test-start","version":true,"type":"shutdown"}\n',
      b'{"startup_id":"test-start","version":2,"type":"shutdown"}\n',
      b'{"startup_id":"test-start","version":1,"type":"unknown"}\n',
      b'{"startup_id":"old","invalid":NaN}\n',
      b"x" * (65536 + 1),
    ]
    for message in cases:
      with self.subTest(message=message[:100]):
        process = await self.launch()
        await self.ready(await self.bound(process))
        process.stdin.write(message)
        await process.stdin.drain()
        await asyncio.wait_for(process.wait(), 15)
        self.assertNotEqual(process.returncode, 0)
        self.assertIn(b"Control protocol error", await process.stderr.read())
        self.assertEqual(await process.stdout.read(), b"")

  async def test_old_startup_is_ignored(self):
    process = await self.launch()
    port = await self.bound(process)
    process.stdin.write(b'{"version":99,"startup_id":"old","type":"shutdown"}\n')
    await process.stdin.drain()
    await self.ready(port)
    process.stdin.close()
    await asyncio.wait_for(process.wait(), 20)
    self.assertEqual(process.returncode, 0)
