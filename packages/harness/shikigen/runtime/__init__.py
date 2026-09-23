"""协议无关的运行环境入口。

按需导出装配入口，避免 persistence 引用 run_state 时反向触发资源装配模块导入。
"""

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
  from shikigen.runtime.composition import Runtime, assemble_runtime, open_runtime

__all__ = ["Runtime", "assemble_runtime", "open_runtime"]


def __getattr__(name: str):
  if name not in __all__:
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
  value = getattr(import_module(f"{__name__}.composition"), name)
  globals()[name] = value
  return value
