"""按稳定 ID 调用工具库的 BaseTool；不持有可执行配置或会话快照。"""

import json
from collections.abc import Awaitable, Callable
from typing import Any, TypeGuard

from langchain_core.messages import ToolCall, ToolMessage
from langchain_core.runnables import RunnableConfig, ensure_config
from langchain_core.tools import BaseTool
from pydantic import Field

from shikigen.contracts.tool_results import ToolResult


class ToolInstance(BaseTool):
  tool_id: str
  execute_fn: Callable[[str, dict], Awaitable[ToolResult]] = Field(
    exclude=True, repr=False
  )
  execute_sync_fn: Callable[[str, dict], ToolResult] = Field(exclude=True, repr=False)

  @staticmethod
  def _is_business_input(
    input: str | dict[str, Any] | ToolCall,
  ) -> TypeGuard[dict[str, Any]]:
    return (
      isinstance(input, dict)
      and input.get("type") == "tool_call"
      and not (
        isinstance(input.get("id"), str)
        and isinstance(input.get("name"), str)
        and isinstance(input.get("args"), dict)
      )
    )

  def invoke(
    self,
    input: str | dict[str, Any] | ToolCall,
    config: RunnableConfig | None = None,
    **kwargs: Any,
  ) -> Any:
    if not self._is_business_input(input):
      return super().invoke(input, config, **kwargs)
    run_config = ensure_config(config)
    return self.run(
      dict(input),
      callbacks=run_config.get("callbacks"),
      tags=run_config.get("tags"),
      metadata=run_config.get("metadata"),
      run_name=run_config.get("run_name"),
      run_id=run_config.pop("run_id", None),
      config=run_config,
      **kwargs,
    )

  async def ainvoke(
    self,
    input: str | dict[str, Any] | ToolCall,
    config: RunnableConfig | None = None,
    **kwargs: Any,
  ) -> Any:
    if not self._is_business_input(input):
      return await super().ainvoke(input, config, **kwargs)
    # LangChain 仅凭 type 判断封装；合法业务对象也可有 type='tool_call'。
    # 非完整封装通过公开 arun 进入同一执行流程，并保留调用上下文。
    run_config = ensure_config(config)
    return await self.arun(
      dict(input),
      callbacks=run_config.get("callbacks"),
      tags=run_config.get("tags"),
      metadata=run_config.get("metadata"),
      run_name=run_config.get("run_name"),
      run_id=run_config.pop("run_id", None),
      config=run_config,
      **kwargs,
    )

  def _to_args_and_kwargs(
    self, tool_input: str | dict[str, Any], tool_call_id: str | None
  ) -> tuple[tuple, dict]:
    # schema 供装配者展示；实际校验交给最新保存定义，且不让 config、
    # run_manager 等合法业务参数被 BaseTool 当成注入参数覆盖。
    if not isinstance(tool_input, dict):
      raise ValueError("Tool instances require an inputs object")
    return (tool_input, tool_call_id), {}

  def _run(self, inputs: dict, tool_call_id: str | None = None):
    return self._format_result(self.execute_sync_fn(self.tool_id, inputs), tool_call_id)

  async def _arun(self, inputs: dict, tool_call_id: str | None = None):
    result = await self.execute_fn(self.tool_id, inputs)
    return self._format_result(result, tool_call_id)

  def _format_result(self, result: ToolResult, tool_call_id: str | None):
    envelope = result.model_dump(mode="json")
    if tool_call_id is None:
      return envelope
    # 普通调用保留完整 dict；模型调用的正文和 artifact 也都保留完整结果，
    # 并将失败投影到 ToolMessage.status，避免 LangChain 默认标记成功。
    return ToolMessage(
      content=json.dumps(envelope, ensure_ascii=False, allow_nan=False),
      artifact=envelope,
      tool_call_id=tool_call_id,
      name=self.name,
      status="success" if result.status == "success" else "error",
    )
