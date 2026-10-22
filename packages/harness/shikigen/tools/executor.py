"""所有消费者共用的执行预算、输入校验和按登记适配器分派的执行入口。"""

import asyncio
import json
import time
from collections.abc import Awaitable, Callable, Mapping

from shikigen.contracts.input_schema import get_schema_validator_class
from shikigen.contracts.tool_execution import (
  ToolAdapter,
  ToolExecution,
  ToolExecutionContext,
)
from shikigen.contracts.tool_results import ToolResult, failure
from shikigen.tools.redaction import execution_secrets, redact_tool_value


class ToolExecutor:
  def __init__(self, adapters: Mapping[str, ToolAdapter]):
    self.adapters = dict(adapters)

  async def execute(
    self,
    load: Callable[[], Awaitable[ToolExecution]],
    inputs: dict,
    *,
    manual_test: bool = False,
  ) -> ToolResult:
    started = time.monotonic()
    context = ToolExecutionContext()
    execution = None
    try:
      # 准备也计入总预算；取得定义后使用其从同一起点计算的截止时间。
      async with asyncio.timeout(30) as budget:
        execution = await load()
        budget.reschedule(started + execution.definition.timeout_seconds)
        if time.monotonic() >= started + execution.definition.timeout_seconds:
          raise TimeoutError
        result = await self._dispatch(execution, inputs, manual_test, context)
    except TimeoutError:
      result = ToolResult(
        status="timeout",
        error={"code": "timeout", "message": "Execution budget exceeded"},
        details=context.details,
      )
    except asyncio.CancelledError:
      result = ToolResult(
        status="cancelled",
        error={"code": "cancelled", "message": "Tool test cancelled"},
        details=context.details,
      )
    except Exception as error:
      result = failure(
        getattr(error, "code", "execution"),
        str(error) if hasattr(error, "code") else "Tool execution failed",
      )
    result.duration_ms = (time.monotonic() - started) * 1000
    if execution is not None:
      secrets = execution_secrets(execution)
      if result.data_available:
        result.data = redact_tool_value(result.data, secrets)
      result.error = redact_tool_value(result.error, secrets)
      result.details = redact_tool_value(result.details, secrets)
    return result

  async def _dispatch(
    self,
    execution: ToolExecution,
    inputs: dict,
    manual_test: bool,
    context: ToolExecutionContext,
  ) -> ToolResult:
    definition = execution.definition
    if not manual_test and not definition.enabled:
      return failure("disabled", "Tool is disabled")
    json.dumps(inputs, allow_nan=False)
    validator_class = get_schema_validator_class(definition.input_schema)
    validator = validator_class(definition.input_schema)
    error = next(validator.iter_errors(inputs), None)
    if error is not None:
      return failure(
        "input_validation", error.message, details={"path": list(error.absolute_path)}
      )
    adapter = self.adapters.get(definition.kind)
    if adapter is None:
      return failure("unsupported_kind", "Tool adapter is not registered")
    return await adapter.execute(execution, inputs, context=context)
