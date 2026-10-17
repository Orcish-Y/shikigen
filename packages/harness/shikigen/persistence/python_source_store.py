"""受管理 Python 源码的文件存取；保存先写新文件，再由工具库提交配置引用。"""

import os
import re
from pathlib import Path, PurePosixPath
from uuid import uuid4

from shikigen.contracts.python_source import PythonSourceError

GENERATED_NAME = re.compile(r"[0-9a-f-]{36}-[0-9a-f]{32}\.py\Z")


class PythonSourceStore:
  def __init__(self, config_path: Path | None):
    self.root = config_path.resolve().parent if config_path else None

  def resolve(self, code_path: str) -> Path:
    relative = PurePosixPath(code_path)
    if (
      self.root is None
      or "\\" in code_path
      or ":" in code_path
      or relative.is_absolute()
      or ".." in relative.parts
      or relative.parts[:2] != ("config", "tools")
      or len(relative.parts) != 3
    ):
      raise PythonSourceError(
        "python_path", "代码路径必须位于配置旁的 config/tools 目录"
      )
    target = self.root.joinpath(*relative.parts)
    if any(part.is_symlink() for part in (target, target.parent, target.parent.parent)):
      raise PythonSourceError("python_path", "代码路径不能使用符号链接")
    if target.resolve().parent != self.root / "config" / "tools":
      raise PythonSourceError("python_path", "代码路径超出受管理目录")
    return target

  def read(self, code_path: str) -> str:
    try:
      return self.resolve(code_path).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
      raise PythonSourceError(
        "python_source_read", "无法读取 Python 源码文件", 503
      ) from error

  def write(self, tool_id: str, source: str) -> str:
    relative = f"config/tools/{tool_id}-{uuid4().hex}.py"
    target = self.resolve(relative)
    try:
      target.parent.mkdir(parents=True, exist_ok=True)
      with target.open("x", encoding="utf-8", newline="") as stream:
        stream.write(source)
        stream.flush()
        os.fsync(stream.fileno())
    except OSError as error:
      raise PythonSourceError(
        "python_source_write", "无法写入 Python 源码文件", 503
      ) from error
    return relative

  def cleanup(self, referenced: set[str]):
    if self.root is None:
      return
    for target in (self.root / "config" / "tools").glob("*.py"):
      relative = target.relative_to(self.root).as_posix()
      if relative in referenced or not GENERATED_NAME.fullmatch(target.name):
        continue
      try:
        self.resolve(relative).unlink(missing_ok=True)
      except (OSError, PythonSourceError):
        # Cleanup cannot turn a confirmed configuration commit into a save failure.
        pass
