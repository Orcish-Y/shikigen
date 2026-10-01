"""Blocking external model boundary for desktop shutdown acceptance."""

import asyncio
import os
from pathlib import Path

from langchain.agents import create_agent
from langchain_core.messages import AIMessage
from runtime_fixtures import ToolModel
from shikigen.core.context import AgentRunContext


class WaitingModel(ToolModel):
  async def _agenerate(self, *args, **kwargs):
    Path("executing").touch()
    try:
      await asyncio.Event().wait()
    finally:
      Path("cleaning").touch()
      if os.environ.get("DESKTOP_TEST_STUCK_CLEANUP"):
        await asyncio.Event().wait()


async def waiting_agent(*, config, middlewares, checkpointer, tool_registry):
  return create_agent(
    WaitingModel(responses=[AIMessage(content="unused")]),
    middleware=middlewares,
    context_schema=AgentRunContext,
    checkpointer=checkpointer,
  )
