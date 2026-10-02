import os
import re
import subprocess
from pathlib import Path

from langchain_core.tools import BaseTool, tool


def create_filesystem_tools(workspace_root: str | Path) -> list[BaseTool]:
  """创建绑定独立工作区的工具；相对根目录以创建时的 cwd 为准。

  根目录须已存在且为目录。绑定后不受进程 cwd 变化影响；shell 仅设置
  执行目录，不提供 sandbox。每次调用返回新的工具实例。
  """
  root = Path(workspace_root).expanduser().resolve()
  if not root.is_dir():
    raise ValueError(f"Workspace root must be an existing directory: {root}")

  def _resolve_workspace_path(path: str) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
      candidate = root / candidate

    resolved_path = candidate.resolve()
    try:
      resolved_path.relative_to(root)
    except ValueError as exc:
      raise ValueError(f"Path must stay within the workspace: {path}") from exc

    return resolved_path

  @tool
  def read_file(path: str) -> str:
    """读取工作区内指定路径的 UTF-8 文件内容。"""
    return _resolve_workspace_path(path).read_text(encoding="utf-8")

  @tool
  def write_file(path: str, content: str) -> str:
    """将内容写入工作区内指定路径的 UTF-8 文件。"""
    file_path = _resolve_workspace_path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content, encoding="utf-8")
    return f"Successfully wrote to file {path}"

  @tool
  def list_dir(path: str = ".") -> str:
    """列出工作区内目录的内容。不传参数时列出根目录。"""
    file_path = _resolve_workspace_path(path)

    if not file_path.is_dir():
      return f"Error: Not a directory: {path}"

    items = sorted(f"{f.name}/" if f.is_dir() else f.name for f in file_path.iterdir())

    return "\n".join(items) if items else "(empty)"

  @tool
  def bash(command: str) -> str:
    """在 workspace 目录下执行一个 shell 命令。

    注意：这是本地执行，不是 sandbox。仅学习用途。
    """
    try:
      result = subprocess.run(
        command,
        shell=True,
        cwd=root,
        capture_output=True,
        text=True,
        errors="replace",
        timeout=30,
      )
    except subprocess.TimeoutExpired:
      return "Error: Command timed out after 30s"

    output = result.stdout + result.stderr
    return output[:4000]

  # Tool descriptions are sent to the model; keep the historical tool name while
  # making the actual shell syntax explicit on each platform.
  bash.description += (
    "\n当前环境是 Windows，命令由 cmd.exe 执行。使用 dir、type 等 cmd 语法；"
    "不要直接使用 Bash 或 PowerShell 语法。需要它们时显式启动相应解释器。"
    if os.name == "nt"
    else "\n当前命令由 /bin/sh 执行，使用 POSIX shell 语法。"
  )

  @tool
  def grep(pattern: str, path: str = ".") -> str:
    """在 workspace 内搜索匹配 pattern 的文件内容。

    Args:
        pattern: 正则表达式或纯文本
        path: 搜索目录（默认 workspace 根目录）
    """
    search_path = _resolve_workspace_path(path)
    try:
      regex = re.compile(pattern)
    except re.error as exc:
      return f"Error: Invalid regular expression: {exc}"

    matches = []
    skipped_directories = {"__pycache__"}

    for file_path in sorted(search_path.rglob("*")):
      if not file_path.is_file():
        continue

      relative_path = file_path.relative_to(root)
      if any(
        part.startswith(".") or part in skipped_directories
        for part in relative_path.parts
      ):
        continue

      try:
        content = file_path.read_text(encoding="utf-8")
      except (OSError, UnicodeDecodeError):
        continue

      for line_number, line in enumerate(content.splitlines(), start=1):
        if regex.search(line):
          matches.append(f"{relative_path}:{line_number}:{line}")

    return "\n".join(matches) if matches else "(no matches)"

  return [read_file, write_file, list_dir, bash, grep]
