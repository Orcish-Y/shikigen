"""桌面控制通道；单个有界读取线程将退出意图交给 asyncio。"""

import asyncio
import json
import logging
import threading
from typing import BinaryIO

MAX_MESSAGE_BYTES = 64 * 1024
logger = logging.getLogger(__name__)


def _invalid_constant(value: str) -> None:
  raise ValueError("Non-finite JSON constant")


class ControlChannel:
  def __init__(self, source: BinaryIO, sink: BinaryIO, startup_id: str):
    self.source = source
    self.sink = sink
    self.startup_id = startup_id
    self.stopping = asyncio.Event()
    self.error: str | None = None

  def send(self, kind: str, **fields: object) -> None:
    message = dict(version=1, startup_id=self.startup_id, type=kind, **fields)
    line = json.dumps(message, ensure_ascii=True).encode("utf-8") + b"\n"
    if len(line) > MAX_MESSAGE_BYTES:
      raise ValueError("Control output exceeds 64 KiB")
    self.sink.write(line)
    self.sink.flush()

  def start(self) -> None:
    loop = asyncio.get_running_loop()

    def stop(error: str | None) -> None:
      self.error = error
      if error:
        logger.error("Control protocol error: %s", error)
      self.stopping.set()

    def read() -> None:
      error = None
      try:
        while True:
          line = self.source.readline(MAX_MESSAGE_BYTES + 1)
          if not line:
            break
          if len(line) > MAX_MESSAGE_BYTES or not line.endswith(b"\n"):
            raise ValueError("Message exceeds 64 KiB or lacks newline")
          try:
            message = json.loads(line.decode("utf-8"), parse_constant=_invalid_constant)
          except (ValueError, UnicodeError, RecursionError) as exc:
            raise ValueError("Invalid UTF-8 JSON control message") from exc
          if not isinstance(message, dict):
            raise ValueError("Control message must be an object")
          if not isinstance(message.get("startup_id"), str):
            raise ValueError("Missing string startup_id")
          if message["startup_id"] != self.startup_id:
            continue
          if (
            type(message.get("version")) is not int
            or message["version"] != 1
            or message.get("type") != "shutdown"
          ):
            raise ValueError("Expected version 1 shutdown message")
          break
      except (OSError, ValueError) as exc:
        error = str(exc)
      finally:
        self.source.close()
      try:
        loop.call_soon_threadsafe(stop, error)
      except RuntimeError:
        pass  # 服务已退出，事件循环已关闭。

    # 不使用默认 executor：启动失败时不能等待仍阻塞于 stdin 的线程。
    threading.Thread(target=read, name="desktop-control", daemon=True).start()
