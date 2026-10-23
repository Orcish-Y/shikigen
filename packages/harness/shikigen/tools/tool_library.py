"""工具库管理与同步／异步调用入口，只更新原始文档中的工具库分组。"""

import asyncio
import hashlib
import json
import logging
import os
import tempfile
import time
from collections.abc import Callable, Generator
from concurrent.futures import Future
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Thread
from uuid import UUID, uuid4

from langchain_core.tools import BaseTool
from pydantic import TypeAdapter, ValidationError

from shikigen.contracts.mcp_connections import AnyMcpConnection, AnyMcpSettings
from shikigen.contracts.python_schema import prepare_python_input_schema
from shikigen.contracts.python_source import PythonSourceError
from shikigen.contracts.tool_definitions import (
  AnyToolDefinition,
  ToolLibraryConfig,
  ToolName,
)
from shikigen.contracts.tool_execution import (
  McpToolExecution,
  PythonToolExecution,
  ToolExecution,
)
from shikigen.contracts.tool_results import ToolResult
from shikigen.core.tool_assembly import create_builtin_registry
from shikigen.persistence.python_source_store import PythonSourceStore
from shikigen.tools.executor import ToolExecutor
from shikigen.tools.http.execution import HttpAdapter
from shikigen.tools.http.openapi_import import selected_openapi_definitions
from shikigen.tools.mcp.execution import McpAdapter
from shikigen.tools.mcp.sessions import (
  McpConnectionSessionProvider,
  list_mcp_session_tools,
  mcp_exception_code,
  mcp_exception_message,
)
from shikigen.tools.python.execution import PythonAdapter
from shikigen.tools.redaction import execution_secrets, redact_tool_value
from shikigen.tools.tool_calls import ToolCallBridge
from shikigen.tools.tool_instance import ToolInstance

definition_adapter = TypeAdapter(AnyToolDefinition)
name_adapter = TypeAdapter(ToolName)
mcp_settings_adapter = TypeAdapter(AnyMcpSettings)
mcp_connection_adapter = TypeAdapter(AnyMcpConnection)
MCP_SOURCE_FIELDS = (
  "connection_id",
  "remote_name",
  "input_schema",
  "output_schema",
  "source_tool",
)
logger = logging.getLogger(__name__)


class ToolLibraryError(ValueError):
  def __init__(
    self,
    code: str,
    message: str,
    status: int = 422,
    *,
    resource_ids: list[str] | None = None,
  ):
    super().__init__(message)
    self.code = code
    self.status = status
    self.resource_ids = resource_ids or []


@dataclass(slots=True)
class ToolTestRecord:
  snapshot: dict
  task: asyncio.Task[None] | None = None


class ToolLibrary:
  def __init__(self, source_path: Path | None):
    self.source_path = source_path.resolve() if source_path else None
    self.python_source_store = PythonSourceStore(self.source_path)
    self._lock = asyncio.Lock()
    self._calls = ToolCallBridge()
    self._reserved_names = set(create_builtin_registry().names) | {"task"}
    self.mcp_session_provider = McpConnectionSessionProvider(
      self.source_path.parent if self.source_path else Path.cwd()
    )
    self.executor = ToolExecutor(
      adapters={
        "http": HttpAdapter(),
        "python": PythonAdapter(),
        "mcp": McpAdapter(self.mcp_session_provider),
      }
    )
    self._test_records: dict[str, ToolTestRecord] = {}
    self._execution_tasks: set[asyncio.Task[ToolResult]] = set()
    self._shutdown_task: asyncio.Task[None] | None = None
    self._discoveries: dict[str, dict] = {}

  def _read(self) -> tuple[dict, ToolLibraryConfig, str]:
    """读取原始配置、工具库，以及覆盖配置与 Python 文件内容的版本。"""
    if self.source_path is None:
      raise ToolLibraryError("config_source", "No loaded configuration source", 503)
    try:
      content = self.source_path.read_bytes()
      raw = json.loads(content)
      if not isinstance(raw, dict):
        raise ValueError("Configuration must be an object")
      library = ToolLibraryConfig.model_validate_json(
        json.dumps(raw.get("tool_library", {}), allow_nan=False)
      )
      ids = [tool.id for tool in library.tools]
      names = [tool.name for tool in library.tools]
      if len(set(ids)) != len(ids) or len(set(names)) != len(names):
        raise ValueError("Duplicate tool identity or name")
      if set(names) & self._reserved_names:
        raise ValueError("Tool name conflicts with a built-in tool")
      config_version = self._configuration_version(content, library)
      return raw, library, config_version
    except (OSError, ValueError, UnicodeError):
      raise ToolLibraryError(
        "config_read", "Cannot read valid tool configuration", 503
      ) from None

  def _configuration_version(self, content: bytes, library: ToolLibraryConfig) -> str:
    """代码内容也属于编辑版本；坏文件仍可列出，详情与执行再定位具体错误。"""
    sources = []
    for tool in library.tools:
      if tool.kind != "python":
        continue
      try:
        source = self.python_source_store.resolve(tool.code_path).read_bytes()
        fingerprint = hashlib.sha256(source).hexdigest()
      except (OSError, PythonSourceError):
        fingerprint = "unreadable"
      sources.append((tool.id, fingerprint))
    return hashlib.sha256(content + json.dumps(sources).encode()).hexdigest()

  def _check_version(self, expected: str | None, current: str, *resource_ids: str):
    if expected != current:
      raise ToolLibraryError(
        "version_conflict",
        "配置或 Python 源码已变化；草稿未提交，请重读后再修改",
        409,
        resource_ids=list(resource_ids),
      )

  async def list_tools(self) -> tuple[list[AnyToolDefinition], str]:
    async with self._coordinate_config():
      _, library, version = await asyncio.to_thread(self._read)
      return library.tools, version

  async def list_mcp_connections(self):
    async with self._coordinate_config():
      _, library, version = await asyncio.to_thread(self._read)
      return list(library.mcp_connections.values()), version

  async def get_mcp_connection(self, connection_id: str):
    connections, version = await self.list_mcp_connections()
    for connection in connections:
      if connection.id == connection_id:
        return connection, version
    raise ToolLibraryError("not_found", "MCP connection does not exist", 404)

  async def inspect_mcp_connection(self, connection_id: str, *, discover: bool):
    async with self._coordinate_config():
      _, library, version = await asyncio.to_thread(self._read)
      connection = library.mcp_connections.get(connection_id)
      if connection is None:
        raise ToolLibraryError("not_found", "MCP connection does not exist", 404)
    budget = (
      connection.discovery_timeout_seconds
      if discover
      else connection.test_timeout_seconds
    )
    started = time.monotonic()
    try:
      async with asyncio.timeout(budget):
        async with self.mcp_session_provider.open_mcp_session(
          connection
        ) as mcp_session:
          initialized = await mcp_session.initialize()
          tools = await list_mcp_session_tools(mcp_session) if discover else []
      observation = {
        "status": "success",
        "connection_id": connection_id,
        "server": initialized.model_dump(mode="json", by_alias=True),
        "duration_ms": (time.monotonic() - started) * 1000,
        "error": None,
      }
      if discover:
        discovery_id = str(uuid4())
        # 发现凭证只驻留当前后端进程，过期/重启后必须重新读取真实来源。
        self._discoveries = {
          key: value
          for key, value in self._discoveries.items()
          if started - value["created"] < 600
        }
        if len(self._discoveries) >= 100:
          self._discoveries.pop(next(iter(self._discoveries)))
        self._discoveries[discovery_id] = {
          "connection_id": connection_id,
          "version": version,
          "tools": tools,
          "created": started,
        }
        existing = {
          tool.remote_name: tool
          for tool in library.tools
          if tool.kind == "mcp" and tool.connection_id == connection_id
        }
        changes = []
        for source in tools:
          previous = existing.pop(source["name"], None)
          changes.append(
            {
              "remote_name": source["name"],
              "status": ("unchanged" if previous.source_tool == source else "changed")
              if previous
              else "new",
              "tool_id": previous.id if previous else None,
              "local_name": previous.name if previous else None,
              "source_tool": source,
              "previous_source_tool": previous.source_tool if previous else None,
            }
          )
        changes.extend(
          {
            "remote_name": tool.remote_name,
            "status": "missing",
            "tool_id": tool.id,
            "local_name": tool.name,
            "source_tool": None,
            "previous_source_tool": tool.source_tool,
          }
          for tool in existing.values()
        )
        observation.update(
          discovery_id=discovery_id, version=version, tools=tools, changes=changes
        )
      return observation
    except TimeoutError:
      return {
        "status": "timeout",
        "connection_id": connection_id,
        "duration_ms": (time.monotonic() - started) * 1000,
        "error": {"code": "timeout", "message": "MCP operation budget exceeded"},
      }
    except Exception as error:
      return {
        "status": "error",
        "connection_id": connection_id,
        "duration_ms": (time.monotonic() - started) * 1000,
        "error": {
          "code": mcp_exception_code(error),
          "message": mcp_exception_message(error),
        },
      }

  async def import_mcp_tools(
    self, connection_id: str, discovery_id: str, selections: list[dict]
  ):
    async with self._coordinate_config():
      raw, library, current_version = await asyncio.to_thread(self._read)
      discovery = self._discoveries.get(discovery_id)
      if (
        not discovery
        or discovery["connection_id"] != connection_id
        or time.monotonic() - discovery["created"] >= 600
      ):
        raise ToolLibraryError(
          "discovery_expired", "Discover this connection again before importing", 409
        )
      # discovery_id 在服务端绑定读取版本，客户端不能替换该版本。
      self._check_version(discovery["version"], current_version, connection_id)
      discovered_tools = {tool["name"]: tool for tool in discovery["tools"]}
      selected_names = [selection["remote_name"] for selection in selections]
      if not selections or len(set(selected_names)) != len(selected_names):
        raise ToolLibraryError("selection_invalid", "Select distinct discovered tools")
      imported = []
      has_changes = False
      for selection in selections:
        remote_name = selection["remote_name"]
        if remote_name not in discovered_tools:
          raise ToolLibraryError(
            "selection_invalid", f"{remote_name}: tool is not in this discovery"
          )
        previous = next(
          (
            tool
            for tool in library.tools
            if tool.kind == "mcp"
            and tool.connection_id == connection_id
            and tool.remote_name == remote_name
          ),
          None,
        )
        source_tool = discovered_tools[remote_name]
        if previous and previous.source_tool == source_tool:
          imported.append(
            {"id": previous.id, "remote_name": remote_name, "existing": True}
          )
          continue
        payload = (
          {
            key: value
            for key, value in previous.model_dump().items()
            if key not in ("id", "created_at", "updated_at")
          }
          if previous
          else {
            "kind": "mcp",
            "connection_id": connection_id,
            "remote_name": remote_name,
            "name": selection["name"],
            "display_name": source_tool.get("title") or remote_name,
            "description": source_tool.get("description") or "",
          }
        )
        payload.update(
          {
            "source_tool": source_tool,
            "input_schema": source_tool["inputSchema"],
            "output_schema": source_tool.get("outputSchema"),
          }
        )
        try:
          tool = self._prepare_tool(payload, library, previous)
        except ToolLibraryError as error:
          raise ToolLibraryError(
            error.code, f"{remote_name}: {error}", error.status
          ) from None
        if previous:
          library.tools = [
            tool if item.id == tool.id else item for item in library.tools
          ]
        else:
          library.tools.append(tool)
        imported.append(
          {"id": tool.id, "remote_name": remote_name, "existing": previous is not None}
        )
        has_changes = True
      if has_changes:
        raw["tool_library"] = library.model_dump(mode="json")
        await asyncio.to_thread(self._commit, raw, current_version)
      return imported

  async def save_mcp_connection(
    self,
    payload: dict,
    *,
    connection_id: str | None = None,
    version: str | None = None,
  ):
    try:
      settings = mcp_settings_adapter.validate_python({"transport": "stdio", **payload})
    except ValidationError:
      raise ToolLibraryError(
        "connection_invalid", "Invalid MCP connection settings"
      ) from None
    async with self._coordinate_config():
      raw, library, current_version = await asyncio.to_thread(self._read)
      previous = library.mcp_connections.get(connection_id) if connection_id else None
      if connection_id and previous is None:
        raise ToolLibraryError("not_found", "MCP connection does not exist", 404)
      if connection_id:
        self._check_version(version, current_version, connection_id)
      now = datetime.now(UTC)
      if previous and previous.transport != settings.transport:
        raise ToolLibraryError(
          "connection_invalid", "Create a new connection to change MCP transport"
        )
      connection = mcp_connection_adapter.validate_python(
        {
          **settings.model_dump(),
          "id": connection_id or str(uuid4()),
          "created_at": previous.created_at if previous else now,
          "updated_at": now,
        }
      )
      library.mcp_connections[connection.id] = connection
      raw["tool_library"] = library.model_dump(mode="json")
      await asyncio.to_thread(self._commit, raw, current_version)
      return connection.id

  async def get_tool(self, tool_id: str) -> tuple[AnyToolDefinition, str]:
    tools, version = await self.list_tools()
    for tool in tools:
      if tool.id == tool_id:
        return tool, version
    raise ToolLibraryError(
      "not_found", f"Tool {tool_id} does not exist", 404, resource_ids=[tool_id]
    )

  async def delete_mcp_connection(self, connection_id: str, version: str) -> None:
    async with self._coordinate_config():
      raw, library, current_version = await asyncio.to_thread(self._read)
      if connection_id not in library.mcp_connections:
        raise ToolLibraryError("not_found", "MCP connection does not exist", 404)
      self._check_version(version, current_version, connection_id)
      del library.mcp_connections[connection_id]
      library.tools = [
        tool
        for tool in library.tools
        if tool.kind != "mcp" or tool.connection_id != connection_id
      ]
      raw["tool_library"] = library.model_dump(mode="json")
      # 已开始的测试持有执行快照，删除只影响此后按 ID 发起的调用。
      await asyncio.to_thread(self._commit, raw, current_version)

  @property
  def reserved_names(self) -> tuple[str, ...]:
    return tuple(sorted(self._reserved_names))

  def _check_name(self, name: object, occupied: set[str]) -> str:
    try:
      validated = name_adapter.validate_python(name, strict=True)
    except ValidationError:
      raise ToolLibraryError(
        "name_invalid",
        "调用名称须为 1–64 个英文字母、数字或下划线，且以字母或下划线开头",
      ) from None
    if validated in occupied:
      raise ToolLibraryError("name_conflict", "调用名称已被其他工具或内置工具占用", 409)
    return validated

  async def validate_name(self, name: str, tool_id: str | None = None):
    tools, _ = await self.list_tools()
    if tool_id is not None and not any(tool.id == tool_id for tool in tools):
      raise ToolLibraryError("not_found", "Tool does not exist", 404)
    occupied = self._reserved_names | {
      tool.name for tool in tools if tool.id != tool_id
    }
    try:
      self._check_name(name, occupied)
    except ToolLibraryError as error:
      return {"valid": False, "code": error.code, "message": str(error)}
    return {"valid": True, "code": None, "message": None}

  async def execute_tool(self, tool_id: str, inputs: dict) -> ToolResult:
    return await self._calls.call(lambda: self._execute_tool(tool_id, inputs))

  async def _execute_tool(self, tool_id: str, inputs: dict) -> ToolResult:
    async def run():
      async def load():
        return await self._load_saved_execution(tool_id)

      result = await self.executor.execute(load, inputs)
      result.details["tool_id"] = tool_id
      return result

    task = asyncio.create_task(run())
    self._execution_tasks.add(task)
    try:
      while True:
        try:
          return await asyncio.shield(task)
        except asyncio.CancelledError:
          if task.cancelled():
            raise
          # 多个调用方的取消或 shutdown 不能重复打断适配器的资源清理。
          if not task.cancelling():
            task.cancel()
    finally:
      self._execution_tasks.discard(task)

  def _execute_tool_sync(self, tool_id: str, inputs: dict) -> ToolResult:
    return self._calls.call_sync(lambda: self.execute_tool(tool_id, inputs))

  async def build_tools(self, tool_ids: list[str]) -> list[BaseTool]:
    """按 ID 装配；名称与 schema 为装配时信息，每次调用仍读取最新定义。"""
    selected_ids = list(dict.fromkeys(tool_ids))
    return await self._calls.call(
      lambda: self._run_coordinated_io(lambda: self._build_tools(selected_ids))
    )

  def _build_tools(self, tool_ids: list[str]) -> list[BaseTool]:
    try:
      _, library, _ = self._read()
    except ToolLibraryError as error:
      raise ToolLibraryError(
        error.code,
        f"Tools {', '.join(tool_ids)}: {error}",
        error.status,
        resource_ids=tool_ids,
      ) from None
    tools: list[BaseTool] = []
    for definition in self._get_executable_definitions(library, tool_ids):
      # 构建时检查源码/连接，但不启动业务操作或保留可执行快照。
      self._prepare_tool_execution(definition, library)
      try:
        tool = ToolInstance(
          tool_id=definition.id,
          name=definition.name,
          description=definition.description,
          args_schema=definition.input_schema,
          metadata={"tool_id": definition.id},
          execute_fn=self.execute_tool,
          execute_sync_fn=self._execute_tool_sync,
        )
      except Exception:
        raise ToolLibraryError(
          "build_failed",
          f"Cannot build tool {definition.name} ({definition.id})",
          resource_ids=[definition.id],
        ) from None
      tools.append(tool)
    return tools

  def _get_executable_definitions(
    self, library: ToolLibraryConfig, tool_ids: list[str]
  ) -> list[AnyToolDefinition]:
    definitions = []
    for tool_id in tool_ids:
      tool = next((item for item in library.tools if item.id == tool_id), None)
      if tool is None:
        raise ToolLibraryError(
          "not_found", f"Tool {tool_id} does not exist", 404, resource_ids=[tool_id]
        )
      if not tool.enabled:
        code, message = "disabled", "Tool is disabled"
      elif tool.kind not in self.executor.adapters:
        code, message = "unsupported_kind", "Tool adapter is not registered"
      else:
        definitions.append(tool)
        continue
      raise ToolLibraryError(
        code, f"{tool.name} ({tool.id}): {message}", resource_ids=[tool.id]
      )
    return definitions

  def _prepare_saved_execution(self, tool_id: str) -> ToolExecution:
    """在同一次协调读取中取得定义、连接和完整源码。"""
    _, library, _ = self._read()
    tool = next((tool for tool in library.tools if tool.id == tool_id), None)
    if tool is None:
      raise ToolLibraryError(
        "not_found", "Tool does not exist", 404, resource_ids=[tool_id]
      )
    return self._prepare_tool_execution(tool, library)

  def _prepare_tool_execution(
    self, tool: AnyToolDefinition, library: ToolLibraryConfig
  ) -> ToolExecution:
    if tool.kind == "python":
      source = self._read_python_source(tool)
      try:
        prepare_python_input_schema(source, tool.input_schema)
      except PythonSourceError as error:
        raise ToolLibraryError(
          error.code,
          f"{tool.name} ({tool.id}): {error}；请重解析并保存",
          error.status,
          resource_ids=[tool.id],
        ) from None
      return PythonToolExecution(definition=tool, source=source)
    if tool.kind == "mcp":
      connection = library.mcp_connections.get(tool.connection_id)
      if connection is None:
        raise ToolLibraryError(
          "not_found",
          f"{tool.name}: MCP connection does not exist",
          404,
          resource_ids=[tool.id, tool.connection_id],
        )
      return McpToolExecution(definition=tool, connection=connection)
    return ToolExecution(definition=tool)

  async def _load_saved_execution(self, tool_id: str) -> ToolExecution:
    return await self._run_coordinated_io(
      lambda: self._prepare_saved_execution(tool_id)
    )

  async def _run_coordinated_io[T](self, operation: Callable[[], T]) -> T:
    async with self._coordinate_config():
      io_task = asyncio.create_task(asyncio.to_thread(operation))
      try:
        return await asyncio.shield(io_task)
      except asyncio.CancelledError:
        # 取消时等工作线程结束，防止文件处理越过协调锁。
        await asyncio.gather(io_task, return_exceptions=True)
        raise

  @asynccontextmanager
  async def _coordinate_config(self):
    self._calls.bind()
    async with self._lock:
      yield

  def _read_python_source(self, tool) -> str:
    try:
      return self.python_source_store.read(tool.code_path)
    except PythonSourceError as error:
      raise ToolLibraryError(
        error.code,
        f"{tool.name} ({tool.id}): {error}",
        error.status,
        resource_ids=[tool.id],
      ) from None

  async def get_tool_detail(self, tool_id: str):
    return await self._run_coordinated_io(lambda: self._read_tool_detail(tool_id))

  def _read_tool_detail(self, tool_id: str):
    _, library, version = self._read()
    tool = next((tool for tool in library.tools if tool.id == tool_id), None)
    if tool is None:
      raise ToolLibraryError(
        "not_found", "Tool does not exist", 404, resource_ids=[tool_id]
      )
    data = tool.model_dump(mode="json")
    if tool.kind == "python":
      data["source"] = self._read_python_source(tool)
    return data, version

  async def cleanup_unused_python_sources(self) -> None:
    """启动时尽力清理残留；后续配置提交仍会重新核对引用并重试。"""
    await self._run_coordinated_io(self._cleanup_python_source_files)

  def _cleanup_python_source_files(self) -> None:
    if self.source_path is None:
      return
    try:
      # 提交后外部编辑器可能再次保存；仅按此刻仍可确认的引用清理。
      _, library, _ = self._read()
      self.python_source_store.cleanup(
        {tool.code_path for tool in library.tools if tool.kind == "python"}
      )
    except (OSError, PythonSourceError, ToolLibraryError):
      logger.warning(
        "Cannot clean unused Python sources; will retry on next cleanup", exc_info=True
      )

  async def get_executable_tool_definitions(
    self, tool_ids: list[str]
  ) -> list[AnyToolDefinition]:
    """按 ID 读取已保存定义，检查存在、启用和适配器支持。"""

    def read():
      _, library, _ = self._read()
      return self._get_executable_definitions(library, tool_ids)

    return await self._run_coordinated_io(read)

  async def delete_tool(self, tool_id: str, version: str) -> None:
    async with self._coordinate_config():
      raw, library, current_config_version = await asyncio.to_thread(self._read)
      if not any(tool.id == tool_id for tool in library.tools):
        raise ToolLibraryError("not_found", "Tool does not exist", 404)
      self._check_version(version, current_config_version, tool_id)
      library.tools = [tool for tool in library.tools if tool.id != tool_id]
      raw["tool_library"] = library.model_dump(mode="json")
      # Code-file cleanup belongs to the managed Python lifecycle; arbitrary
      # code_path values must never cause deletion of user files.
      await asyncio.to_thread(self._commit, raw, current_config_version)

  async def start_test(self, tool_id: str, inputs: dict):
    self._calls.check_open()
    execution = await self._load_saved_execution(tool_id)
    return self._start_test(execution, inputs, tool_id)

  async def start_draft_test(
    self,
    payload: dict,
    inputs: dict,
    tool_id: str | None = None,
  ):
    self._calls.check_open()
    async with self._coordinate_config():
      _, library, _ = await asyncio.to_thread(self._read)
      previous = next((tool for tool in library.tools if tool.id == tool_id), None)
      if tool_id is not None and previous is None:
        raise ToolLibraryError("not_found", "Tool does not exist", 404)
      self._check_tool_edit_permissions(payload, previous)
      payload, source = self._prepare_python_payload(payload)
      tool = self._prepare_tool(payload, library, previous)
      if tool.kind == "python":
        assert source is not None
        execution = PythonToolExecution(definition=tool, source=source)
      elif tool.kind == "mcp":
        connection = library.mcp_connections.get(tool.connection_id)
        if connection is None:
          raise ToolLibraryError("not_found", "MCP connection does not exist", 404)
        execution = McpToolExecution(definition=tool, connection=connection)
      else:
        execution = ToolExecution(definition=tool)
    return self._start_test(execution, inputs, tool_id)

  def _create_test_record(
    self,
    tool_id: str | None,
    inputs: dict,
  ) -> ToolTestRecord:
    if len(self._test_records) >= 100:
      completed = next(
        (
          key
          for key, record in self._test_records.items()
          if record.task is None and record.snapshot["status"] != "running"
        ),
        None,
      )
      if completed is None:
        raise ToolLibraryError("busy", "Too many active tool tests", 503)
      del self._test_records[completed]
    test_id = str(uuid4())
    snapshot = {
      "test_id": test_id,
      "tool_id": tool_id,
      "status": "running",
      "created_at": datetime.now(UTC).isoformat(),
      "result": None,
      "cancel_requested": False,
      "inputs": inputs,
    }
    record = ToolTestRecord(snapshot=snapshot)
    self._test_records[test_id] = record
    return record

  def _start_test(
    self,
    execution: ToolExecution,
    inputs: dict,
    tool_id: str | None,
  ):
    # 准备期间可能已关闭；检查到任务登记之间不能让出所属事件循环。
    self._calls.check_open()
    observed_inputs = redact_tool_value(inputs, execution_secrets(execution))
    record = self._create_test_record(tool_id, observed_inputs)
    snapshot = record.snapshot

    async def load():
      return execution

    started = time.monotonic()

    async def run():
      result = await self.executor.execute(load, inputs, manual_test=True)
      snapshot.update(status=result.status, result=result.model_dump(mode="json"))

    def finished(task: asyncio.Task[None]):
      # 任务在第一次调度前被取消时，协程内的异常处理尚未开始。
      if task.cancelled():
        result = ToolResult(
          status="cancelled",
          error={"code": "cancelled", "message": "Tool test cancelled"},
          duration_ms=(time.monotonic() - started) * 1000,
        )
        snapshot.update(status=result.status, result=result.model_dump(mode="json"))
      record.task = None

    task = asyncio.create_task(run())
    record.task = task
    task.add_done_callback(finished)
    return dict(snapshot)

  def _get_test_record(self, test_id: str):
    try:
      test_id = str(UUID(test_id))
    except ValueError:
      raise ToolLibraryError("not_found", "Tool test does not exist", 404) from None
    if test_id not in self._test_records:
      raise ToolLibraryError("not_found", "Tool test does not exist", 404)
    return self._test_records[test_id]

  def get_test(self, test_id: str):
    return dict(self._get_test_record(test_id).snapshot)

  async def cancel_test(self, test_id: str):
    record = self._get_test_record(test_id)
    task = record.task
    if task is not None:
      self._request_test_cancellation(record)
      try:
        await asyncio.shield(task)
      except asyncio.CancelledError:
        if not task.cancelled():
          raise
    return dict(record.snapshot)

  def _request_test_cancellation(self, record: ToolTestRecord):
    task = record.task
    snapshot = record.snapshot
    if task is not None and not task.done() and not snapshot["cancel_requested"]:
      snapshot["cancel_requested"] = True
      # 不在超时或另一取消的资源清理期间再次注入取消。
      if not task.cancelling():
        task.cancel()

  async def shutdown(self):
    self._calls.bind()
    if self._shutdown_task is None:
      self._calls.close()
      self._shutdown_task = asyncio.create_task(self._shutdown())
    caller_cancelled = False
    while True:
      try:
        await asyncio.shield(self._shutdown_task)
        break
      except asyncio.CancelledError:
        if self._shutdown_task.cancelled():
          raise
        # 重复取消只记录在调用方，不能再次打断共享任务的资源清理。
        caller_cancelled = True
    if caller_cancelled:
      raise asyncio.CancelledError

  async def _shutdown(self):
    tasks = []
    for record in tuple(self._test_records.values()):
      if record.task is not None:
        tasks.append(record.task)
        self._request_test_cancellation(record)
    for task in tuple(self._execution_tasks):
      tasks.append(task)
      if not task.done() and not task.cancelling():
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)

  async def save_tool(
    self,
    payload: dict,
    *,
    tool_id: str | None = None,
    version: str | None = None,
  ) -> tuple[AnyToolDefinition, str]:
    async with self._coordinate_config():
      raw, library, current_config_version = await asyncio.to_thread(self._read)
      previous = next((tool for tool in library.tools if tool.id == tool_id), None)
      if tool_id is not None and previous is None:
        raise ToolLibraryError("not_found", "Tool does not exist", 404)
      if tool_id is not None:
        self._check_version(version, current_config_version, tool_id)
      self._check_tool_edit_permissions(payload, previous)
      payload, source = self._prepare_python_payload(payload)
      tool = self._prepare_tool(payload, library, previous)
      if source is not None and tool.kind == "python":
        tool.code_path = await asyncio.to_thread(
          self.python_source_store.write, tool.id, source
        )
      library.tools = [tool if item.id == tool.id else item for item in library.tools]
      if previous is None:
        library.tools.append(tool)
      raw["tool_library"] = library.model_dump(mode="json")
      saved_version = await asyncio.to_thread(self._commit, raw, current_config_version)
      return tool, saved_version

  async def import_openapi_tools(
    self, document: str, selections: list[dict], version: str
  ):
    definitions = await asyncio.to_thread(
      selected_openapi_definitions, document, selections
    )
    async with self._coordinate_config():
      raw, library, current_version = await asyncio.to_thread(self._read)
      self._check_version(
        version, current_version, *[item["operation_key"] for item in selections]
      )
      imported = []
      for selection, definition in zip(selections, definitions, strict=True):
        self._check_tool_edit_permissions(definition, None)
        try:
          tool = self._prepare_tool(definition, library, None)
        except ToolLibraryError as error:
          raise ToolLibraryError(
            error.code, f"{selection['operation_key']}：{error}", error.status
          ) from None
        library.tools.append(tool)
        imported.append({"id": tool.id})
      raw["tool_library"] = library.model_dump(mode="json")
      await asyncio.to_thread(self._commit, raw, current_version)
      return imported

  def _prepare_python_payload(self, payload: dict) -> tuple[dict, str | None]:
    """只解析本次提交的 Python 草稿，不读取或修改持久状态及传入对象。"""
    if payload.get("kind") != "python":
      return payload, None
    if "code_path" in payload:
      raise ToolLibraryError("read_only", "代码路径由系统管理，请提交 source")
    source = payload.get("source")
    schema = prepare_python_input_schema(source, payload.get("input_schema", ...))
    definition = {key: value for key, value in payload.items() if key != "source"}
    definition["input_schema"] = schema
    return definition, source

  def _check_tool_edit_permissions(
    self, payload: dict, previous: AnyToolDefinition | None
  ) -> None:
    """普通保存和草稿测试的编辑限制；发现更新使用自己的来源核对。"""
    if previous is None and payload.get("kind") == "mcp":
      raise ToolLibraryError("read_only", "MCP tools must be selected from discovery")
    if {"id", "created_at", "updated_at"} & payload.keys():
      raise ToolLibraryError(
        "read_only", "ID and timestamps are maintained by the system"
      )
    if previous and payload.get("kind", previous.kind) != previous.kind:
      raise ToolLibraryError("read_only", "Tool type cannot be changed")
    if previous and previous.kind == "mcp":
      for field in MCP_SOURCE_FIELDS:
        if payload.get(field, getattr(previous, field)) != getattr(previous, field):
          raise ToolLibraryError(
            "read_only", "MCP source fields require discovery updates"
          )

  def _prepare_tool(
    self,
    payload: dict,
    library: ToolLibraryConfig,
    previous: AnyToolDefinition | None,
  ) -> AnyToolDefinition:
    """校验定义并准备系统字段；调用方负责普通编辑或发现更新的权限核对。"""
    occupied = self._reserved_names | {
      tool.name for tool in library.tools if previous is None or tool.id != previous.id
    }
    if not isinstance(payload.get("display_name"), str):
      raise ToolLibraryError("definition_invalid", "Page name must be a string")
    name = self._check_name(payload.get("name"), occupied)
    now = datetime.now(UTC)
    definition = {
      **payload,
      "name": name,
      "id": previous.id if previous else str(uuid4()),
      "created_at": previous.created_at if previous else now,
      "updated_at": now,
    }
    if definition.get("kind") == "python":
      # 满足持久定义模型的必填字段；草稿只用源码快照，保存时替换为实际写入路径。
      definition["code_path"] = "config/tools/pending.py"
    if previous:
      if previous.kind != "python":
        definition.setdefault("kind", previous.kind)
      if previous.kind == "mcp":
        for field in MCP_SOURCE_FIELDS:
          definition.setdefault(field, getattr(previous, field))
    try:
      if previous and previous.kind == "http":
        definition.setdefault("auth", previous.model_dump(mode="json")["auth"])
        definition.setdefault("openapi_source", previous.openapi_source)
      return definition_adapter.validate_python(definition)
    except ValidationError as error:
      details = "; ".join(
        f"{'.'.join(map(str, item['loc']))}: "
        + (
          "Invalid discriminator value"
          if item["type"] == "union_tag_invalid"
          else item["msg"]
        )
        for item in error.errors(include_input=False, include_context=False)
      )
      raise ToolLibraryError("definition_invalid", details) from None

  def _commit(self, raw: dict, expected_version: str):
    assert self.source_path is not None
    temporary_path = None
    content = (
      json.dumps(raw, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    ).encode("utf-8")
    try:
      with tempfile.NamedTemporaryFile(
        mode="wb", delete=False, dir=self.source_path.parent
      ) as target:
        temporary_path = Path(target.name)
        target.write(content)
        target.flush()
        os.fsync(target.fileno())
      saved_version = self._configuration_version(
        content, ToolLibraryConfig.model_validate_json(json.dumps(raw["tool_library"]))
      )
      _, _, current_version = self._read()
      self._check_version(
        expected_version,
        current_version,
        *[tool["id"] for tool in raw["tool_library"]["tools"]],
      )
      os.replace(temporary_path, self.source_path)
      # 配置替换就是提交点；清理失败只记录日志，后续提交或启动再重试。
      self._cleanup_python_source_files()
      return saved_version
    except OSError as error:
      raise ToolLibraryError(
        "config_write", "Cannot save tool configuration", 503
      ) from error
    finally:
      if temporary_path is not None:
        try:
          temporary_path.unlink(missing_ok=True)
        except OSError:
          # A best-effort temporary-file cleanup cannot change commit outcome.
          pass


class SyncToolLibrary:
  """ToolLibrary 的同步调用视图，执行统一转交给所属事件循环。"""

  def __init__(self, library: ToolLibrary):
    self._library = library

  def build_tools(self, tool_ids: list[str]) -> list[BaseTool]:
    return self._library._calls.call_sync(lambda: self._library.build_tools(tool_ids))

  def execute_tool(self, tool_id: str, inputs: dict) -> ToolResult:
    return self._library._calls.call_sync(
      lambda: self._library.execute_tool(tool_id, inputs)
    )


@contextmanager
def open_sync_tool_library(source_path: Path | None) -> Generator[SyncToolLibrary]:
  """在 with 期间复用一个后台循环；退出前停止执行并回收子进程等资源。"""
  ready: Future[tuple[ToolLibrary, asyncio.AbstractEventLoop, asyncio.Event]] = Future()

  async def serve():
    library = ToolLibrary(source_path)
    library._calls.bind()
    stop = asyncio.Event()
    ready.set_result((library, asyncio.get_running_loop(), stop))
    await stop.wait()

  def run():
    try:
      with asyncio.Runner() as runner:
        runner.run(serve())
    except BaseException as error:
      if not ready.done():
        ready.set_exception(error)
      else:
        raise

  thread = Thread(target=run, name="shikigen-tools")
  thread.start()
  try:
    library, loop, stop = ready.result()
    try:
      yield SyncToolLibrary(library)
    finally:
      library._calls.call_sync(library.shutdown)
  finally:
    # 启动期间被中断也要等装配结束，再让后台循环退出。
    try:
      library, loop, stop = ready.result()
      loop.call_soon_threadsafe(stop.set)
    finally:
      thread.join()
