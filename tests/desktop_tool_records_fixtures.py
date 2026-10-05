"""第 08 票：真实工具节点／middleware／持久事实，模型为无网络固定响应。"""

import asyncio
from pathlib import Path

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import tool
from runtime_fixtures import ToolModel
from shikigen.core.context import AgentRunContext

LONG_RESULT = "  **工具原文不渲染**\n" + "\n".join(
  f"{i}: " + "长行" * 100 for i in range(100)
)
ARTIFACTS = {
  "first": "",
  "second": 0,
  "failed": {"values": [0, False, None], "path": "images/error.png"},
  "empty-array": [],
  "empty-object": {},
  "false": False,
  "null": None,
}
CASES = [
  "first",
  "second",
  "failed",
  "empty-array",
  "empty-object",
  "false",
  "null",
  "waiting",
]


@tool
async def record_fixture(case: str) -> ToolMessage:
  """Return a complete literal tool record for desktop verification."""
  await asyncio.sleep(0.15 if case == "second" else 0.3)
  if case == "failed":
    while not Path("allow-tool-results").exists():
      await asyncio.sleep(0.05)
  # A mismatching explicit result ID exercises an independent tool result and
  # leaves the original call waiting even after the run completes.
  identity = "fixture-orphan" if case == "waiting" else f"fixture-{case}"
  content = (
    LONG_RESULT
    if case == "failed"
    else "Error: this is a successful ToolMessage"
    if case == "second"
    else [{"type": "unknown", "text": "完整未知结果", "fields": [0, False]}]
    if case == "waiting"
    else []
    if case == "empty-array"
    else ""
  )
  return ToolMessage(
    tool_call_id=identity,
    name="different_result_name" if case == "first" else "record_fixture",
    status="error" if case == "failed" else "success",
    content=content,
    **({"artifact": ARTIFACTS[case]} if case in ARTIFACTS else {}),
  )


async def tool_records_agent(*, config, middlewares, checkpointer, tool_registry):
  model = ToolModel(
    responses=[
      AIMessage(
        content="工具完整记录验收",
        tool_calls=[
          {"id": f"fixture-{case}", "name": "record_fixture", "args": {"case": case}}
          for case in CASES
        ],
      ),
      AIMessage(content="工具记录已产生；工具失败不代表运行失败。"),
    ]
  )
  return create_agent(
    model,
    tools=[record_fixture],
    middleware=middlewares,
    context_schema=AgentRunContext,
    checkpointer=checkpointer,
  )
