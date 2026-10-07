"""桌面入口：python -m app.desktop --config ... --startup-id ... --port ..."""

import argparse
import asyncio
import logging
import os
import socket
import sys
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING

from dotenv import load_dotenv
from shikigen.app_config import AppConfig, load_app_config

from app.desktop_control import ControlChannel
from app.desktop_network import bind_listener, get_desktop_frontend_origins

if TYPE_CHECKING:
  from shikigen.runtime import Runtime

PROJECT_ROOT = Path(__file__).resolve().parents[1]
logger = logging.getLogger(__name__)


async def serve_backend(
  config: AppConfig, listener: socket.socket, control: ControlChannel
) -> None:
  from shikigen.runtime import open_runtime

  async def lifetime() -> None:
    # 初始化、运行与资源释放始终由同一个任务持有。
    async with open_runtime(config) as runtime:
      if not control.stopping.is_set():
        await _serve_runtime(runtime, listener, control)

  if control.stopping.is_set():
    return
  active = asyncio.create_task(lifetime())
  stopping = asyncio.create_task(control.stopping.wait())
  try:
    await asyncio.wait({active, stopping}, return_when=asyncio.FIRST_COMPLETED)
  finally:
    stopping.cancel()
    with suppress(asyncio.CancelledError):
      await stopping
    # 无论收到停止请求还是调用方取消，都请求结束生命周期并等待收尾。
    if not active.done():
      active.cancel()
    with suppress(asyncio.CancelledError):
      await active


async def _serve_runtime(
  runtime: "Runtime", listener: socket.socket, control: ControlChannel
) -> None:
  import uvicorn
  from fastapi.middleware.cors import CORSMiddleware

  from app.server import create_app

  app = create_app(runtime=runtime)
  # Desktop WebView origins; ordinary HTTP/CLI entry points keep their policy.
  app.add_middleware(
    CORSMiddleware,
    allow_origins=get_desktop_frontend_origins(),
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
    expose_headers=["Retry-After"],
  )

  @app.get("/health/ready")
  async def ready():
    from fastapi.responses import JSONResponse

    if control.stopping.is_set():
      return JSONResponse({"status": "stopping"}, status_code=503)
    return {"version": 1, "startup_id": control.startup_id, "status": "ready"}

  server = uvicorn.Server(
    uvicorn.Config(
      app,
      host="127.0.0.1",
      reload=False,
      workers=1,
      log_config=None,
    )
  )
  serving = asyncio.create_task(server.serve(sockets=[listener]))
  try:
    # 取消生命周期时进入 finally，HTTP 服务仍需完成正常关闭。
    await asyncio.shield(serving)
  finally:
    server.should_exit = True
    try:
      # Stop admission and executions immediately, so persistent SSE can finish.
      await runtime.lifecycle.shutdown()
    finally:
      # Keep storage and data locks alive until HTTP requests have also ended.
      await serving


async def run(control: ControlChannel, config_path: Path, start_port: int) -> int:
  control.start()
  try:
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    config = load_app_config(config_path)
    with bind_listener(start_port) as listener:
      bound_port = listener.getsockname()[1]
      control.send("bound", port=bound_port)
      await serve_backend(config, listener, control)
    return 1 if control.error else 0
  except Exception as error:
    logger.exception("Desktop backend failed")
    control.send("startup_error", code=type(error).__name__, message=str(error)[:4000])
    return 1


def main() -> None:
  # 保留独立的协议句柄，将普通 print、库日志及后代 stdout 导向 stderr。
  output = os.fdopen(os.dup(sys.stdout.fileno()), "wb", buffering=0)
  os.set_inheritable(output.fileno(), False)
  os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
  logging.basicConfig(level=logging.INFO, stream=sys.stderr)
  # 配置日志
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--config", type=Path, required=True)
  parser.add_argument("--startup-id", required=True)
  parser.add_argument(
    "--port",
    dest="start_port",
    type=int,
    required=True,
    help="后端起始端口；占用后递增尝试",
  )
  args = parser.parse_args()
  with output:
    # 独立的无缓冲描述符由 daemon 线程持有，避免解释器退出等待 stdin 缓冲锁。
    source = os.fdopen(os.dup(sys.stdin.fileno()), "rb", buffering=0)
    os.set_inheritable(source.fileno(), False)
    control = ControlChannel(source, output, args.startup_id)
    raise SystemExit(asyncio.run(run(control, args.config, args.start_port)))


if __name__ == "__main__":
  main()
