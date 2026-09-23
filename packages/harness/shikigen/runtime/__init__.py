"""协议无关的运行环境入口。

按需导出装配入口，导入运行管理子模块时不提前加载完整资源装配。
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
