import asyncio
import unittest
from datetime import UTC, datetime
from unittest.mock import patch

import httpx
from shikigen.contracts.python_source import PythonSourceError
from shikigen.contracts.tool_definitions import (
  HttpToolDefinition,
  PythonToolDefinition,
  ToolDefinition,
)
from shikigen.contracts.tool_execution import (
  PythonToolExecution,
  ToolExecution,
  ToolExecutionContext,
)
from shikigen.contracts.tool_results import ToolResult
from shikigen.tools.adapter.http_execution import HttpAdapter
from shikigen.tools.adapter.python_execution import PythonAdapter
from shikigen.tools.library_execution import ToolExecutor


def definition(**overrides) -> ToolDefinition:
  return ToolDefinition.model_validate(
    {
      "id": "tool-id",
      "kind": "registered",
      "name": "registered_tool",
      "display_name": "已登记适配器",
      "created_at": datetime.now(UTC),
      "updated_at": datetime.now(UTC),
      **overrides,
    }
  )


def loader(execution: ToolExecution):
  async def load():
    return execution

  return load


class RecordingAdapter:
  def __init__(self):
    self.calls: list[tuple[ToolExecution, dict, ToolExecutionContext]] = []

  async def execute(self, execution, inputs, *, context):
    self.calls.append((execution, inputs, context))
    context.details.update(inputs)
    await asyncio.sleep(0)
    return ToolResult(status="success", data=inputs, details=context.details)


class WaitingAdapter:
  def __init__(self):
    self.started = asyncio.Event()
    self.release = asyncio.Event()

  async def execute(self, execution, inputs, *, context):
    self.started.set()
    try:
      await self.release.wait()
    finally:
      context.details.update(stdout="before stop", exit_code=-1, cleaned=True)
    return ToolResult(status="success")


class ToolExecutorTests(unittest.IsolatedAsyncioTestCase):
  async def test_registered_adapter_uses_shared_interface_and_per_call_context(self):
    adapter = RecordingAdapter()
    executor = ToolExecutor(adapters={"python": adapter})
    tool = PythonToolDefinition(
      **definition(
        kind="python",
        input_schema={"type": "object", "properties": {"call": {"type": "string"}}},
      ).model_dump(),
      code_path="config/tools/unused.py",
    )
    first_execution = PythonToolExecution(definition=tool, source="first source")
    second_execution = PythonToolExecution(definition=tool, source="second source")
    first, second = await asyncio.gather(
      executor.execute(loader(first_execution), {"call": "first"}),
      executor.execute(loader(second_execution), {"call": "second"}),
    )
    self.assertEqual(first.status, "success")
    self.assertEqual(second.status, "success")
    self.assertEqual(first.details, {"call": "first"})
    self.assertEqual(second.details, {"call": "second"})
    self.assertIsNot(adapter.calls[0][2], adapter.calls[1][2])
    self.assertIs(adapter.calls[0][0], first_execution)
    self.assertIs(adapter.calls[1][0], second_execution)
    self.assertGreaterEqual(first.duration_ms, 0)

  async def test_disabled_invalid_and_unregistered_tools_do_not_call_adapter(self):
    adapter = RecordingAdapter()
    executor = ToolExecutor(adapters={"registered": adapter})
    disabled = definition(enabled=False)
    result = await executor.execute(loader(ToolExecution(disabled)), {})
    assert result.error is not None
    self.assertEqual(result.error["code"], "disabled")
    invalid = definition(
      input_schema={
        "type": "object",
        "properties": {"count": {"type": "integer"}},
        "required": ["count"],
      }
    )
    result = await executor.execute(loader(ToolExecution(invalid)), {"count": "3"})
    assert result.error is not None
    self.assertEqual(result.error["code"], "input_validation")
    self.assertEqual(result.details["path"], ["count"])
    result = await executor.execute(
      loader(ToolExecution(definition(kind="missing"))), {}
    )
    assert result.error is not None
    self.assertEqual(result.error["code"], "unsupported_kind")
    self.assertEqual(adapter.calls, [])
    result = await executor.execute(
      loader(ToolExecution(disabled)), {}, manual_test=True
    )
    self.assertEqual(result.status, "success")
    self.assertEqual(len(adapter.calls), 1)

  async def test_empty_registration_does_not_create_default_adapters(self):
    result = await ToolExecutor(adapters={}).execute(
      loader(ToolExecution(definition())), {}
    )
    assert result.error is not None
    self.assertEqual(result.error["code"], "unsupported_kind")

  async def test_timeout_keeps_adapter_cleanup_details(self):
    adapter = WaitingAdapter()
    executor = ToolExecutor(adapters={"registered": adapter})
    result = await executor.execute(
      loader(ToolExecution(definition(timeout_seconds=1))), {}
    )
    self.assertEqual(result.status, "timeout")
    self.assertEqual(result.details["stdout"], "before stop")
    self.assertEqual(result.details["exit_code"], -1)
    self.assertTrue(result.details["cleaned"])

  async def test_cancellation_keeps_adapter_cleanup_details(self):
    adapter = WaitingAdapter()
    executor = ToolExecutor(adapters={"registered": adapter})
    task = asyncio.create_task(
      executor.execute(loader(ToolExecution(definition())), {})
    )
    await asyncio.wait_for(adapter.started.wait(), timeout=5)
    task.cancel()
    result = await task
    self.assertEqual(result.status, "cancelled")
    self.assertEqual(result.details["stdout"], "before stop")
    self.assertTrue(result.details["cleaned"])

  async def test_loading_errors_preserve_domain_codes(self):
    async def missing_source():
      raise PythonSourceError("python_source_read", "无法读取源码", 503)

    result = await ToolExecutor(adapters={}).execute(missing_source, {})
    assert result.error is not None
    self.assertEqual(result.status, "error")
    self.assertEqual(result.error["code"], "python_source_read")
    self.assertEqual(result.error["message"], "无法读取源码")

  async def test_http_transport_failure_is_translated_by_http_adapter(self):
    async def unreachable(request):
      raise httpx.ConnectError("unreachable", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(unreachable))
    self.addAsyncCleanup(client.aclose)
    tool = HttpToolDefinition(
      **definition(kind="http").model_dump(), url="http://example.test/"
    )
    with patch(
      "shikigen.tools.adapter.http_execution.httpx.AsyncClient", return_value=client
    ):
      result = await ToolExecutor(adapters={"http": HttpAdapter()}).execute(
        loader(ToolExecution(tool)), {}
      )
    self.assertEqual(result.status, "error")
    assert result.error is not None
    self.assertEqual(result.error["code"], "transport")

  async def test_python_adapter_requires_source_in_prepared_execution(self):
    tool = PythonToolDefinition(
      **definition(kind="python").model_dump(), code_path="config/tools/unused.py"
    )
    result = await ToolExecutor(adapters={"python": PythonAdapter()}).execute(
      loader(ToolExecution(tool)), {}
    )
    assert result.error is not None
    self.assertEqual(result.error["code"], "configuration")


if __name__ == "__main__":
  unittest.main()
