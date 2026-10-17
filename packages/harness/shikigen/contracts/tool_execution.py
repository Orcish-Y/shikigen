"""执行器与类型适配器共用的调用接口；运行依赖由装配处提供。"""

from dataclasses import dataclass, field
from typing import Protocol

from pydantic import JsonValue

from shikigen.contracts.tool_definitions import PythonToolDefinition, ToolDefinition
from shikigen.contracts.tool_results import ToolResult


@dataclass(frozen=True, slots=True)
class ToolExecution:
  """已准备完成的执行对象；类型专属资源由对应子类声明。"""

  definition: ToolDefinition


@dataclass(frozen=True, slots=True)
class PythonToolExecution(ToolExecution):
  """定义和本次源码快照；源码必填，不在执行期间回退到持久文件。"""

  definition: PythonToolDefinition
  source: str


@dataclass(frozen=True, slots=True)
class ToolExecutionContext:
  """每次调用独立的执行信息；清理时写入的信息供超时/取消返回。"""

  details: dict[str, JsonValue] = field(default_factory=dict)


class ToolAdapter(Protocol):
  async def execute(
    self,
    execution: ToolExecution,
    inputs: dict,
    *,
    context: ToolExecutionContext,
  ) -> ToolResult: ...
