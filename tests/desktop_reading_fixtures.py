"""第 09 票：真实 Agent/middleware 的长正文与可控流，不访问模型网络。"""

import asyncio
import os
from pathlib import Path

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGenerationChunk
from langchain_core.tools import tool
from runtime_fixtures import ToolModel
from shikigen.core.context import AgentRunContext

CODE = "\n".join(f"reading_line_{i} = {i}" for i in range(90))
LONG_BODY = (
  "阅读开始\n\n"
  + "\n\n".join(
    f"段落 {i}：" + "用于验证阅读位置和窗口宽度变化。" * 8 for i in range(36)
  )
  + "\n\n```python\n"
  + CODE
  + "\n```\n\n"
)
TAIL = (
  "阅读完成\n\n"
  + "\n\n".join(f"末尾段落 {i}" for i in range(20))
  + "\n\n```python\n"
  + CODE
  + "\n```"
)


class ReadingModel(ToolModel):
  calls: int = 0

  async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
    response = self.responses[self.i]
    self.i = (self.i + 1) % len(self.responses)
    yield ChatGenerationChunk(message=AIMessageChunk(content=response.content))
    if response.tool_calls:
      self.calls += 1
      calls = [
        {**item, "id": f"reading-call-{self.calls}"} for item in response.tool_calls
      ]
      Path("reading-stream-started").touch()
      while not Path("allow-reading-stream").exists():
        await asyncio.sleep(0.05)
      for i in range(12):
        yield ChatGenerationChunk(
          message=AIMessageChunk(content=f"\n\n新增段落 {i}：持续流式内容。")
        )
        await asyncio.sleep(0.025)
      yield ChatGenerationChunk(message=AIMessageChunk(content="", tool_calls=calls))


@tool("reading_result")
def reading_result() -> str:
  """Return a literal result used to resize the tool card."""
  return "\n".join(f"工具记录 {i}" for i in range(80))


@tool("bash")
def approval_result() -> str:
  """A deterministic action that requires approval in the normal middleware."""
  return "已审批"


async def reading_agent(*, config, middlewares, checkpointer, tool_registry):
  name = "bash" if os.environ.get("DESKTOP_TEST_READING_APPROVAL") else "reading_result"
  return create_agent(
    ReadingModel(
      responses=[
        AIMessage(
          content=LONG_BODY,
          tool_calls=[{"id": "reading-call", "name": name, "args": {}}],
        ),
        AIMessage(content=TAIL),
      ]
    ),
    tools=[reading_result, approval_result],
    middleware=middlewares,
    context_schema=AgentRunContext,
    checkpointer=checkpointer,
  )
