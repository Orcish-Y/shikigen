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
