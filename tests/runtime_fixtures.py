"""确定性真实 Agent：运行模型节点、工具和持久化 middleware，不访问网络。"""

from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from langchain_core.tools import tool
from shikigen.runtime_context import AgentRunContext


class ToolModel(FakeMessagesListChatModel):
  def bind_tools(self, tools, **kwargs):
    return self


@tool
def add(a: int, b: int) -> int:
  """Add two integers."""
  return a + b


async def deterministic_agent(*, config, middlewares, checkpointer):
  model = ToolModel(
    responses=[
      AIMessage(
        content="",
        tool_calls=[{"id": "call-1", "name": "add", "args": {"a": 1, "b": 2}}],
      ),
      AIMessage(content="3"),
    ]
  )
  return create_agent(
    model,
    tools=[add],
    middleware=middlewares,
    context_schema=AgentRunContext,
    checkpointer=checkpointer,
  )
