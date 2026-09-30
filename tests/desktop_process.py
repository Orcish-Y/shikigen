"""运行真实桌面入口，仅以确定性 Agent 替代模型边界。"""

import os
import socket
import subprocess
import sys
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime_fixtures import deterministic_agent

from app import desktop


async def agent(**kwargs):
  print("fixture ordinary stdout")
  subprocess.run(
    [sys.executable, "-c", "print('fixture child stdout')"],
    check=True,
    stdin=subprocess.DEVNULL,
  )
  return await deterministic_agent(**kwargs)


original_bind = socket.socket.bind
bound_once = False


def bind(sock, address):
  global bound_once
  if not isinstance(address, tuple) or address[1] == 0:
    return original_bind(sock, address)  # asyncio 在 Windows 上的唤醒 socket。
  fault = os.environ.get("DESKTOP_TEST_BIND_ERROR")
  if fault:
    del os.environ["DESKTOP_TEST_BIND_ERROR"]
    raise OSError(int(fault), "injected socket error")
  if bound_once:
    raise AssertionError("Backend tried to rebind its socket")
  result = original_bind(sock, address)
  bound_once = True
  return result


with ExitStack() as stack:
  stack.enter_context(patch("socket.socket.bind", new=bind))
  stack.enter_context(
    patch(
      "shikigen.runtime.composition.create_lead_agent",
      new=agent,
    )
  )
  if root := os.environ.get("DESKTOP_TEST_ENV_ROOT"):
    stack.enter_context(patch.object(desktop, "PROJECT_ROOT", Path(root)))
  desktop.main()
