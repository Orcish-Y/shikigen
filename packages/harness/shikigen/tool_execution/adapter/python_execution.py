"""Python 工具适配器：使用后端解释器执行源码副本；本机权限，不是安全沙箱。"""

import asyncio
import json
import os
import subprocess
import sys
import tempfile
from collections import deque
from pathlib import Path

from shikigen.contracts.python_schema import prepare_python_input_schema
from shikigen.contracts.tool_execution import (
  PythonToolExecution,
  ToolExecution,
  ToolExecutionContext,
)
from shikigen.contracts.tool_results import ToolResult, failure

DEBUG_LIMIT = 64 * 1024


class PythonAdapter:
  async def execute(
    self,
    execution: ToolExecution,
    inputs: dict,
    *,
    context: ToolExecutionContext,
  ) -> ToolResult:
    if not isinstance(execution, PythonToolExecution):
      return failure("configuration", "Expected a prepared Python tool execution")
    definition = execution.definition
    source = execution.source
    details = context.details
    prepare_python_input_schema(source, definition.input_schema)
    with tempfile.TemporaryDirectory(prefix="shikigen-python-") as directory:
      work = Path(directory)
      (work / "source.py").write_text(source, encoding="utf-8")
      (work / "inputs.json").write_text(
        json.dumps(inputs, allow_nan=False), encoding="utf-8"
      )
      process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-u",
        str(Path(__file__).with_name("python_worker.py")),
        str(work / "source.py"),
        str(work / "inputs.json"),
        str(work / "result.json"),
        cwd=work,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
      )
      chunks = deque()
      size = 0
      truncated = set()

      async def drain(stream, channel):
        nonlocal size
        while chunk := await stream.read(8192):
          chunks.append((channel, chunk))
          size += len(chunk)
          while size > DEBUG_LIMIT:
            name, oldest = chunks.popleft()
            remove = min(size - DEBUG_LIMIT, len(oldest))
            truncated.add(name)
            size -= remove
            if remove < len(oldest):
              chunks.appendleft((name, oldest[remove:]))

      readers = [
        asyncio.create_task(drain(process.stdout, "stdout")),
        asyncio.create_task(drain(process.stderr, "stderr")),
      ]
      try:
        await process.wait()
        await asyncio.gather(*readers)
      finally:
        if process.returncode is None:
          process.kill()
        await process.wait()
        for task in readers:
          if not task.done():
            task.cancel()
        await asyncio.gather(*readers, return_exceptions=True)
        details.update(exit_code=process.returncode)
        for channel in ("stdout", "stderr"):
          details[channel] = b"".join(
            chunk for name, chunk in chunks if name == channel
          ).decode("utf-8", errors="ignore")
          details[channel + "_truncated"] = channel in truncated
      protocol = work / "result.json"
      if process.returncode != 0 or not protocol.is_file():
        return failure(
          "python_exit", "Python 子进程异常退出或未返回结果", details=details
        )
      if protocol.stat().st_size > 1024 * 1024 + 8192:
        return failure("output_limit", "Python 返回值超过 1 MiB", details=details)
      try:
        result = json.loads(protocol.read_text(encoding="utf-8"))
        if "error" in result:
          return ToolResult(status="error", error=result["error"], details=details)
        return ToolResult(status="success", data=result["data"], details=details)
      except (ValueError, KeyError):
        return failure("python_protocol", "无法读取 Python 返回协议", details=details)
