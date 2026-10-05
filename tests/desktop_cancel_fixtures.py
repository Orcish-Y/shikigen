"""第 10 票真实 Agent：固定正文、可控生成结束和审批，不访问供应商。"""

import asyncio
import os
from pathlib import Path

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGenerationChunk
from langchain_core.tools import tool
from runtime_fixtures import ToolModel
from shikigen.core.context import AgentRunContext

PARTS = [
  "  取消保存验收：第一段正文\n\n",
  "```python\n" + "\n".join(f"cancel_line_{i} = {i}" for i in range(60)) + "\n```",
  "\n\n最后一段已接入正文\n    原始空白保留 \n",
]
BODY = "".join(PARTS)


class CancelModel(ToolModel):
  calls: int = 0

  async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
    self.calls += 1
    identity = f"cancel-answer-{self.calls}"
    for part in PARTS:
      yield ChatGenerationChunk(message=AIMessageChunk(id=identity, content=part))
      await asyncio.sleep(0.025)
    Path("cancel-text-ready").touch()
    while not Path("allow-cancel-model").exists():
      await asyncio.sleep(0.05)
    if os.environ.get("DESKTOP_TEST_CANCEL_APPROVAL"):
      yield ChatGenerationChunk(
        message=AIMessageChunk(
          id=identity,
          content="",
          tool_calls=[{"id": f"cancel-call-{self.calls}", "name": "bash", "args": {}}],
        )
      )


@tool("bash")
def approval_operation() -> str:
  """A real approval action; cancellation must never execute this tool."""
  Path("cancel-side-effect").touch()
  return "执行完成"


async def cancel_agent(*, config, middlewares, checkpointer, tool_registry):
  return create_agent(
    CancelModel(responses=[AIMessage(content=BODY)]),
    tools=[approval_operation],
    middleware=middlewares,
    context_schema=AgentRunContext,
    checkpointer=checkpointer,
  )
