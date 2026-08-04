import re
import subprocess
from pathlib import Path

from langchain_core.tools import tool

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent


def _resolve_workspace_path(path: str) -> Path:
  candidate = Path(path)
  if not candidate.is_absolute():
    candidate = WORKSPACE_ROOT / candidate

  resolved_path = candidate.resolve()
  try:
    resolved_path.relative_to(WORKSPACE_ROOT)
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
      cwd=WORKSPACE_ROOT,
      capture_output=True,
      text=True,
      timeout=30,
    )
  except subprocess.TimeoutExpired:
    return "Error: Command timed out after 30s"

  output = result.stdout + result.stderr
  return output[:4000]


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

    relative_path = file_path.relative_to(WORKSPACE_ROOT)
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
