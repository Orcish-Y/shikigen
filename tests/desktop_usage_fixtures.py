"""第17票离线真实 Agent：零、未知及两个实际模型回调的累计用量。"""

import asyncio
from pathlib import Path

from langchain.agents import create_agent
from langchain_core.messages import AIMessage
from runtime_fixtures import ToolModel, add
from shikigen.core.context import AgentRunContext

MODEL_A = "实际模型-A-" + "long-model-name-" * 12
MODEL_B = "实际模型-B"


class UsageModel(ToolModel):
  completed_callback_count: int = 0

  async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
    if Path("hold-usage-model").exists():
      Path("usage-model-ready").touch()
      while not Path("allow-usage-model").exists():
        await asyncio.sleep(0.05)
    result = await super()._agenerate(messages, stop, run_manager, **kwargs)
    self.completed_callback_count += 1
    message = result.generations[0].message.model_copy(deep=True)
    message.id = f"{message.id}-{self.completed_callback_count}"
    for tool_call in message.tool_calls:
      tool_call["id"] = f"{tool_call['id']}-{self.completed_callback_count}"
    result.generations[0].message = message
    model_name = result.generations[0].message.response_metadata.get("model_name")
    if model_name:
      result.llm_output = {"model_name": model_name}
    return result


def create_usage_response(
  identity, text, input_tokens, output_tokens, model_name=None, **kwargs
):
  return AIMessage(
    id=identity,
    content=text,
    usage_metadata={
      "input_tokens": input_tokens,
      "output_tokens": output_tokens,
      "total_tokens": input_tokens + output_tokens,
    },
    response_metadata={"model_name": model_name} if model_name else {},
    **kwargs,
  )


async def usage_agent(*, config, middlewares, checkpointer, tool_registry):
  responses = (
    [create_usage_response("usage-zero", "真实零用量已完成", 0, 0)]
    if Path("zero-usage-model").exists()
    else [
      create_usage_response(
        "usage-tools",
        "",
        6,
        4,
        MODEL_A,
        tool_calls=[{"id": "usage-add", "name": "add", "args": {"a": 1, "b": 2}}],
      ),
      create_usage_response("usage-answer", "真实多模型用量已完成", 9, 8, MODEL_B),
    ]
  )
  return create_agent(
    UsageModel(responses=responses),
    tools=[add],
    middleware=middlewares,
    context_schema=AgentRunContext,
    checkpointer=checkpointer,
  )
