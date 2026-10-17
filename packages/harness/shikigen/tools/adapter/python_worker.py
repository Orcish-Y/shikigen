"""Python 适配器的子进程入口。返回文件与 stdout/stderr 调试通道分离。"""

import inspect
import json
import math
import runpy
import sys
import traceback
from pathlib import Path

OUTPUT_LIMIT = 1024 * 1024


def strict_json(value):
  if value is None or type(value) in (str, bool, int):
    return
  if type(value) is float:
    if not math.isfinite(value):
      raise ValueError("返回值包含 NaN 或 Infinity")
    return
  if type(value) is list:
    for item in value:
      strict_json(item)
    return
  if type(value) is dict and all(type(key) is str for key in value):
    for item in value.values():
      strict_json(item)
    return
  raise TypeError("main 必须返回严格 JSON 值")


def run(source_path, inputs_path):
  try:
    namespace = runpy.run_path(source_path, run_name="__tool__")
    entry = namespace.get("main")
    if (
      not inspect.isfunction(entry)
      or inspect.iscoroutinefunction(entry)
      or inspect.isgeneratorfunction(entry)
      or entry.__name__ != "main"
    ):
      return {
        "error": {"code": "python_entry", "message": "实际入口不是同步 main 函数"}
      }
    inputs = json.loads(Path(inputs_path).read_text(encoding="utf-8"))
    try:
      inspect.signature(entry, follow_wrapped=False).bind(**inputs)
    except TypeError as error:
      return {"error": {"code": "python_binding", "message": str(error)}}
    value = entry(**inputs)
    try:
      strict_json(value)
      content = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as error:
      return {"error": {"code": "python_return", "message": str(error)}}
    if len(content) > OUTPUT_LIMIT:
      return {"error": {"code": "output_limit", "message": "Python 返回值超过 1 MiB"}}
    return {"data": value}
  except BaseException as error:
    traceback.print_exc()
    return {
      "error": {
        "code": "python_runtime",
        "message": f"{type(error).__name__}: {error}"[:4000],
      }
    }


if __name__ == "__main__":
  result = run(sys.argv[1], sys.argv[2])
  Path(sys.argv[3]).write_text(
    json.dumps(result, ensure_ascii=False, allow_nan=False), encoding="utf-8"
  )
