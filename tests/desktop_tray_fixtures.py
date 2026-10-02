"""Controlled external model boundary for real desktop residency acceptance."""

import asyncio
import os
from pathlib import Path

from langchain.agents import create_agent
from langchain_core.messages import AIMessage
from runtime_fixtures import ToolModel
from shikigen.core.context import AgentRunContext


class ResidentModel(ToolModel):
  async def _agenerate(self, *args, **kwargs):
    Path("executing").touch()
    while not Path("continue-task").exists():
      await asyncio.sleep(0.05)
    if os.environ.get("DESKTOP_TEST_TASK_FAILURE"):
      raise RuntimeError("acceptance task failure")
    return await super()._agenerate(*args, **kwargs)


async def resident_agent(*, config, middlewares, checkpointer, tool_registry):
  return create_agent(
    ResidentModel(responses=[AIMessage(content="后台任务已完成")]),
    middleware=middlewares,
    context_schema=AgentRunContext,
    checkpointer=checkpointer,
  )
