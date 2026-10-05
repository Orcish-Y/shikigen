"""第 11 票：真实 Agent 在接入长正文后执行失败，离线可控。"""

import asyncio
import uuid
from pathlib import Path

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGenerationChunk
from runtime_fixtures import ToolModel
from shikigen.core.context import AgentRunContext

PARTS = [
  "  失败保存验收：第一段正文\n\n",
  "```python\n" + "\n".join(f"failure_line_{i} = {i}" for i in range(60)) + "\n```",
  "\n\n最后一段失败前已接入正文\n    原始空白保留 \n",
]
BODY = "".join(PARTS)
ERROR = (
  "供应商执行异常 request-123\n"
  + "\n".join(f"  真实失败详情 {i}：保留实际错误原文；" for i in range(120))
  + "\n末尾错误原文 "
)


class FailureModel(ToolModel):
  async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
    identity = "failure-answer-" + uuid.uuid4().hex
    for part in PARTS:
      yield ChatGenerationChunk(message=AIMessageChunk(id=identity, content=part))
      await asyncio.sleep(0.025)
    Path("failure-text-ready").touch()
    while not Path("allow-failure-model").exists():
      await asyncio.sleep(0.05)
    raise RuntimeError(ERROR)


async def failure_agent(*, config, middlewares, checkpointer, tool_registry):
  return create_agent(
    FailureModel(responses=[AIMessage(content=BODY)]),
    tools=[],
    middleware=middlewares,
    context_schema=AgentRunContext,
    checkpointer=checkpointer,
  )
