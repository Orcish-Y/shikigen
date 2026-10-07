"""桌面后端的监听绑定和前端来源策略。"""

import errno
import logging
import os
import socket
import sys
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)


def get_desktop_frontend_origins() -> list[str]:
  dev_origin = os.environ.get("SHIKIGEN_DESKTOP_DEV_ORIGIN", "http://127.0.0.1:5173")
  origin_parts = urlsplit(dev_origin)
  if (
    origin_parts.scheme not in {"http", "https"}
    or not origin_parts.hostname
    or "*" in origin_parts.netloc
    or origin_parts.username is not None
    or origin_parts.password is not None
    or origin_parts.path
    or origin_parts.query
    or origin_parts.fragment
    or dev_origin != f"{origin_parts.scheme}://{origin_parts.netloc}"
    or origin_parts.port == 0
  ):
    raise ValueError("SHIKIGEN_DESKTOP_DEV_ORIGIN must be an HTTP(S) origin")
  return [dev_origin, "http://tauri.localhost"]


def bind_listener(start_port: int) -> socket.socket:
  """从起始端口递增并保留绑定；只跳过占用及 Windows 10013 错误。"""
  if not 1 <= start_port <= 65535:
    raise ValueError("start_port must be between 1 and 65535")
  for candidate_port in range(start_port, 65536):
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
      if sys.platform == "win32":
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
      listener.bind(("127.0.0.1", candidate_port))
      listener.setblocking(False)
      return listener
    except OSError as error:
      listener.close()
      error_code = getattr(error, "winerror", None) or error.errno
      if error_code == 10013:
        logger.warning("Cannot bind 127.0.0.1:%s: %s", candidate_port, error)
      elif error_code not in (errno.EADDRINUSE, 10048):
        raise
  raise OSError("No available backend port through 65535")
