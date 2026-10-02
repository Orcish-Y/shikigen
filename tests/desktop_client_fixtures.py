"""Real approval replay with a deterministic model and a controlled async tool."""

import asyncio
from pathlib import Path

from langchain.agents import create_agent
from langchain_core.messages import AIMessage
from langchain_core.tools import tool
from runtime_fixtures import ToolModel
from shikigen.core.context import AgentRunContext


async def approval_agent(*, config, middlewares, checkpointer, tool_registry):
  @tool("bash")
  async def approved_work() -> str:
    """Perform work after approval."""
    Path("resumed-executing").touch()
    while not Path("continue-task").exists():
      await asyncio.sleep(0.05)
    return "approved work complete"

  return create_agent(
    ToolModel(
      responses=[
        AIMessage(
          content="",
          tool_calls=[
            {
              "id": "approved-call",
              "name": "bash",
              "args": {},
            }
          ],
        ),
        AIMessage(content="审批后任务完成"),
      ]
    ),
    tools=[approved_work],
    middleware=middlewares,
    context_schema=AgentRunContext,
    checkpointer=checkpointer,
  )
