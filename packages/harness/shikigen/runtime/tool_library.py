"""从实际配置来源读取工具，只更新原始文档中的工具库分组。"""

import asyncio
import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from pydantic import TypeAdapter, ValidationError

from shikigen.contracts.tool_definitions import (
  AnyToolDefinition,
  ToolLibraryConfig,
  ToolName,
)
from shikigen.tools.library_execution import ToolExecutor
from shikigen.tools.tool_registry import create_builtin_registry

definition_adapter = TypeAdapter(AnyToolDefinition)
name_adapter = TypeAdapter(ToolName)


class ToolLibraryError(ValueError):
  def __init__(self, code: str, message: str, status: int = 422):
    super().__init__(message)
    self.code = code
    self.status = status


class ToolLibrary:
  def __init__(self, source_path: Path | None):
    self.source_path = source_path
    self._lock = asyncio.Lock()
    self._reserved_names = set(create_builtin_registry().names) | {"task"}
    self.executor = ToolExecutor()
    self._tests: dict[str, dict] = {}
    self._tasks: dict[str, asyncio.Task] = {}

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
    except (OSError, ValueError, UnicodeError) as error:
      raise ToolLibraryError(
        "config_read", "Cannot read valid tool configuration", 503
      ) from error

  async def list_tools(self) -> tuple[list[AnyToolDefinition], str]:
    async with self._lock:
      _, library, version = await asyncio.to_thread(self._read)
      return library.tools, version

  async def get_tool(self, tool_id: str) -> tuple[AnyToolDefinition, str]:
    tools, version = await self.list_tools()
    for tool in tools:
      if tool.id == tool_id:
        return tool, version
    raise ToolLibraryError("not_found", "Tool does not exist", 404)

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
      return tool

    return await self.executor.execute(load, inputs)

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
      return await asyncio.to_thread(self._commit, raw, current_config_version)

  async def start_test(self, tool_id: str, inputs: dict):
    # Resolve before admission. A corrupt/deleted definition must never use cache.
    tool, _ = await self.get_tool(tool_id)
    return self._start_test(tool, inputs, tool_id)

  async def start_draft_test(
    self, payload: dict, inputs: dict, tool_id: str | None = None
  ):
    async with self._lock:
      _, library, _ = await asyncio.to_thread(self._read)
      previous = next((tool for tool in library.tools if tool.id == tool_id), None)
      self._check_tool_edit_permissions(payload, previous)
      tool = self._prepare_tool(payload, library, tool_id)
    return self._start_test(tool, inputs, tool_id)

  def _start_test(self, tool: AnyToolDefinition, inputs: dict, tool_id: str | None):
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
      return tool

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
    self, payload: dict, *, tool_id: str | None = None, version: str | None = None
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
      tool = self._prepare_tool(payload, library, tool_id)
      library.tools = [tool if item.id == tool.id else item for item in library.tools]
      if previous is None:
        library.tools.append(tool)
      raw["tool_library"] = library.model_dump(mode="json")
      saved_version = await asyncio.to_thread(self._commit, raw, current_config_version)
      return tool, saved_version

  def _check_tool_edit_permissions(
    self, payload: dict, previous: AnyToolDefinition | None
  ) -> None:
    """普通保存和草稿测试的编辑限制；发现更新使用自己的来源核对。"""
    if previous and previous.kind == "mcp":
      for field in ("server_id", "remote_name", "input_schema", "output_schema"):
        if payload.get(field, getattr(previous, field)) != getattr(previous, field):
          raise ToolLibraryError(
            "read_only", "MCP source fields require discovery updates"
          )

  def _prepare_tool(
    self, payload: dict, library: ToolLibraryConfig, tool_id: str | None
  ) -> AnyToolDefinition:
    """校验定义并准备系统字段；调用方负责普通编辑或发现更新的权限核对。"""
    previous = next((tool for tool in library.tools if tool.id == tool_id), None)
    if tool_id is not None and previous is None:
      raise ToolLibraryError("not_found", "Tool does not exist", 404)
    if {"id", "created_at", "updated_at"} & payload.keys():
      raise ToolLibraryError(
        "read_only", "ID and timestamps are maintained by the system"
      )
    if previous and payload.get("kind", previous.kind) != previous.kind:
      raise ToolLibraryError("read_only", "Tool type cannot be changed")
    occupied = self._reserved_names | {
      tool.name for tool in library.tools if tool.id != tool_id
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
    if previous:
      definition.setdefault("kind", previous.kind)
      if previous.kind == "mcp":
        for field in ("server_id", "remote_name", "input_schema", "output_schema"):
          definition.setdefault(field, getattr(previous, field))
    try:
      return definition_adapter.validate_python(definition)
    except ValidationError as error:
      details = "; ".join(
        f"{'.'.join(map(str, item['loc']))}: {item['msg']}"
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
