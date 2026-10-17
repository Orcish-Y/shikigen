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
    try:
      execution = await load()
      async with asyncio.timeout(execution.definition.timeout_seconds):
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
