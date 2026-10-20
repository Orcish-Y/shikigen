"""从实际配置来源读取工具，只更新原始文档中的工具库分组。"""

import asyncio
import hashlib
import json
import os
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from pydantic import TypeAdapter, ValidationError

from shikigen.contracts.mcp_connections import AnyMcpConnection, AnyMcpSettings
from shikigen.contracts.python_schema import prepare_python_input_schema
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
from shikigen.core.tool_assembly import create_builtin_registry
from shikigen.persistence.python_source_store import PythonSourceStore
from shikigen.tool_execution.adapter.http_execution import HttpAdapter
from shikigen.tool_execution.adapter.mcp_execution import McpAdapter
from shikigen.tool_execution.adapter.python_execution import PythonAdapter
from shikigen.tool_execution.executor import ToolExecutor
from shikigen.tool_execution.mcp.sessions import (
  McpConnectionSessionProvider,
  list_mcp_session_tools,
  mcp_exception_code,
  mcp_exception_message,
)

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


class ToolLibraryError(ValueError):
  def __init__(self, code: str, message: str, status: int = 422):
    super().__init__(message)
    self.code = code
    self.status = status


class ToolLibrary:
  def __init__(self, source_path: Path | None):
    self.source_path = source_path.resolve() if source_path else None
    self.python_source_store = PythonSourceStore(self.source_path)
    self._lock = asyncio.Lock()
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
    self._tests: dict[str, dict] = {}
    self._tasks: dict[str, asyncio.Task] = {}
    self._discoveries: dict[str, dict] = {}

  def _read(self) -> tuple[dict, ToolLibraryConfig, str]:
    """读取原始配置、工具库和配置文件内容的 SHA-256 版本标识。"""
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
      config_version = hashlib.sha256(content).hexdigest()
      return raw, library, config_version
    except (OSError, ValueError, UnicodeError):
      raise ToolLibraryError(
        "config_read", "Cannot read valid tool configuration", 503
      ) from None

  async def list_tools(self) -> tuple[list[AnyToolDefinition], str]:
    async with self._lock:
      _, library, version = await asyncio.to_thread(self._read)
      return library.tools, version

  async def list_mcp_connections(self):
    async with self._lock:
      _, library, version = await asyncio.to_thread(self._read)
      return list(library.mcp_connections.values()), version

  async def get_mcp_connection(self, connection_id: str):
    connections, version = await self.list_mcp_connections()
    for connection in connections:
      if connection.id == connection_id:
        return connection, version
    raise ToolLibraryError("not_found", "MCP connection does not exist", 404)

  async def inspect_mcp_connection(self, connection_id: str, *, discover: bool):
    async with self._lock:
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
    async with self._lock:
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
      if discovery["version"] != current_version:
        raise ToolLibraryError(
          "version_conflict",
          "Configuration changed; discover again before importing",
          409,
        )
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
    async with self._lock:
      raw, library, current_version = await asyncio.to_thread(self._read)
      previous = library.mcp_connections.get(connection_id) if connection_id else None
      if connection_id and previous is None:
        raise ToolLibraryError("not_found", "MCP connection does not exist", 404)
      if connection_id and version != current_version:
        raise ToolLibraryError(
          "version_conflict", "Configuration changed; reload before saving", 409
        )
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
    raise ToolLibraryError("not_found", "Tool does not exist", 404)

  async def delete_mcp_connection(self, connection_id: str, version: str) -> None:
    async with self._lock:
      raw, library, current_version = await asyncio.to_thread(self._read)
      if connection_id not in library.mcp_connections:
        raise ToolLibraryError("not_found", "MCP connection does not exist", 404)
      if version != current_version:
        raise ToolLibraryError(
          "version_conflict", "Configuration changed; reload before deleting", 409
        )
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

  async def execute_tool(self, tool_id: str, inputs: dict):
    async def load():
      tool, _ = await self.get_tool(tool_id)
      return await self._load_saved_execution(tool)

    return await self.executor.execute(load, inputs)

  async def _load_saved_execution(self, tool: AnyToolDefinition) -> ToolExecution:
    """读取持久资源，形成完整执行快照；适配器只消费准备后的数据。"""
    if tool.kind == "python":
      source = await asyncio.to_thread(self.python_source_store.read, tool.code_path)
      return PythonToolExecution(definition=tool, source=source)
    if tool.kind == "mcp":
      connection, _ = await self.get_mcp_connection(tool.connection_id)
      return McpToolExecution(definition=tool, connection=connection)
    return ToolExecution(definition=tool)

  async def get_tool_detail(self, tool_id: str):
    tool, version = await self.get_tool(tool_id)
    data = tool.model_dump(mode="json")
    if tool.kind == "python":
      data["source"] = await asyncio.to_thread(
        self.python_source_store.read, tool.code_path
      )
    return data, version

  def _cleanup_python_source_files(self, library: ToolLibraryConfig):
    self.python_source_store.cleanup(
      {tool.code_path for tool in library.tools if tool.kind == "python"}
    )

  async def get_executable_tool_definitions(
    self, tool_ids: list[str]
  ) -> list[AnyToolDefinition]:
    """按 ID 读取已保存定义，检查存在、启用和适配器支持。"""
    tools, _ = await self.list_tools()
    definitions = []
    for tool_id in tool_ids:
      tool = next((item for item in tools if item.id == tool_id), None)
      if tool is None:
        raise ToolLibraryError("not_found", "Tool does not exist", 404)
      if not tool.enabled:
        raise ToolLibraryError("disabled", "Tool is disabled")
      if tool.kind not in self.executor.adapters:
        raise ToolLibraryError("unsupported_kind", "Tool adapter is not registered")
      definitions.append(tool)
    return definitions

  async def delete_tool(self, tool_id: str, version: str) -> str:
    async with self._lock:
      raw, library, current_config_version = await asyncio.to_thread(self._read)
      if not any(tool.id == tool_id for tool in library.tools):
        raise ToolLibraryError("not_found", "Tool does not exist", 404)
      if version != current_config_version:
        raise ToolLibraryError(
          "version_conflict", "Configuration changed; reload before deleting", 409
        )
      library.tools = [tool for tool in library.tools if tool.id != tool_id]
      raw["tool_library"] = library.model_dump(mode="json")
      # Code-file cleanup belongs to the managed Python lifecycle; arbitrary
      # code_path values must never cause deletion of user files.
      saved_version = await asyncio.to_thread(self._commit, raw, current_config_version)
      await asyncio.to_thread(self._cleanup_python_source_files, library)
      return saved_version

  async def start_test(self, tool_id: str, inputs: dict):
    # Resolve before admission. A corrupt/deleted definition must never use cache.
    tool, _ = await self.get_tool(tool_id)
    execution = await self._load_saved_execution(tool)
    return self._start_test(execution, inputs, tool_id)

  async def start_draft_test(
    self, payload: dict, inputs: dict, tool_id: str | None = None
  ):
    async with self._lock:
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

  def _start_test(
    self,
    execution: ToolExecution,
    inputs: dict,
    tool_id: str | None,
  ):
    test_id = str(uuid4())
    snapshot = {
      "test_id": test_id,
      "tool_id": tool_id,
      "status": "running",
      "created_at": datetime.now(UTC).isoformat(),
      "result": None,
    }
    # Keep only this session's most recent completed observations (no history store).
    if len(self._tests) >= 100:
      completed = next((key for key in self._tests if key not in self._tasks), None)
      if completed is not None:
        del self._tests[completed]
      else:
        raise ToolLibraryError("busy", "Too many active tool tests", 503)
    self._tests[test_id] = snapshot

    async def load():
      return execution

    async def run():
      result = await self.executor.execute(load, inputs, manual_test=True)
      snapshot.update(status=result.status, result=result.model_dump(mode="json"))
      self._tasks.pop(test_id, None)

    self._tasks[test_id] = asyncio.create_task(run())
    return dict(snapshot)

  def get_test(self, test_id: str):
    if test_id not in self._tests:
      raise ToolLibraryError("not_found", "Tool test does not exist", 404)
    return dict(self._tests[test_id])

  async def shutdown(self):
    tasks = list(self._tasks.values())
    for task in tasks:
      task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)

  async def save_tool(
    self,
    payload: dict,
    *,
    tool_id: str | None = None,
    version: str | None = None,
  ) -> tuple[AnyToolDefinition, str]:
    async with self._lock:
      raw, library, current_config_version = await asyncio.to_thread(self._read)
      previous = next((tool for tool in library.tools if tool.id == tool_id), None)
      if tool_id is not None and previous is None:
        raise ToolLibraryError("not_found", "Tool does not exist", 404)
      if tool_id is not None and version != current_config_version:
        raise ToolLibraryError(
          "version_conflict", "Configuration changed; reload before saving", 409
        )
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
      await asyncio.to_thread(self._cleanup_python_source_files, library)
      return tool, saved_version

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
      if hashlib.sha256(self.source_path.read_bytes()).hexdigest() != expected_version:
        raise ToolLibraryError(
          "version_conflict", "Configuration changed before commit", 409
        )
      os.replace(temporary_path, self.source_path)
      return hashlib.sha256(content).hexdigest()
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
