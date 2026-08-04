# 沙箱工具：bash, list_dir, grep

补全了文件操作工具集，agent 现在可以执行 shell 命令、浏览目录、搜索代码。

**实现**：
- `bash(command)` — `subprocess.run(shell=True, timeout=30)`，stdout+stderr 合并截断 4000 字符
- `list_dir(path)` — `Path.iterdir()`，目录加 `/` 后缀，按名排序
- `grep(pattern, path)` — 纯 Python 实现（`re.compile` + `rglob`），跳过 `.` 前缀目录和 `__pycache__`，try/except UnicodeDecodeError
- 所有工具复用 `_resolve_workspace_path()` 的路径安全检查（`Path.relative_to()` 防逃逸）

**遇到的 bug**：
- `from asyncio import subprocess` 错误导入 — asyncio.subprocess 无 `run()` 函数，应为标准库 `import subprocess`
- `grep` 初版不跳过 `.git`/`.venv`/`__pycache__` 和二进制文件
- `list_dir` 非目录时返回 `"(Empty)"` 误导，改为 `"Error: Not a directory"`

**Evidence**: `tools/filesystem.py` (111 行)
