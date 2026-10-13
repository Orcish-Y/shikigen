"""真实 Agent 推理事实与可控正文流；不访问模型网络或扩展推理流协议。"""

import asyncio
from pathlib import Path

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGenerationChunk
from langchain_core.tools import tool
from runtime_fixtures import ToolModel
from shikigen.core.context import AgentRunContext

INTRO = "\n\n".join(
  f"推理前段落 {index}：" + "用来核对正文更新期间的阅读锚点。" * 8
  for index in range(12)
)
REASONING_TEXT = (
  "  **模型提供的推理原文**\n\n"
  + "\n\n".join(
    f"推理段落 {index}：保留实际内容、用户选择和原始记录。" for index in range(24)
  )
  + "\n\n```python\n  enabled = False\n  count = 0\n```\n\n"
  + "说明[^1]\n\n[^1]: 推理脚注原文。\n\n"
  + "<script>window.__reasoningInjected = true</script>\n\n"
  + "![远程图片](https://example.org/not-loaded.png)\n尾部空白  \n"
)
MODEL_CONTENT = [
  {"type": "text", "text": INTRO},
  {
    "type": "reasoning",
    "reasoning": REASONING_TEXT,
    "signature": "original-reasoning-signature",
  },
  {"type": "reasoning", "reasoning": "  "},
  {"type": "reasoning", "encrypted_content": "opaque", "values": [0, False, None]},
  {"type": "unknown", "text": "未知推理块保留 JSON", "values": [0, False, None]},
]
# Fixed public LangChain v3 message representation. Standard blocks acquire
# indexes, unknown provider blocks retain their original value, and the tool
# call is also represented as a content block. Native checks compare these
# actual persisted facts, not the producer's pre-normalization representation.
SAVED_CONTENT = [
  {"type": "text", "text": INTRO, "index": 0},
  {
    "type": "reasoning",
    "reasoning": REASONING_TEXT,
    "signature": "original-reasoning-signature",
    "index": 1,
  },
  {"type": "reasoning", "reasoning": "  ", "index": 2},
  {
    "type": "reasoning",
    "encrypted_content": "opaque",
    "values": [0, False, None],
    "index": 3,
  },
  {
    "type": "non_standard",
    "value": {
      "type": "unknown",
      "text": "未知推理块保留 JSON",
      "values": [0, False, None],
    },
    "index": 4,
  },
  {
    "type": "tool_call",
    "id": "reasoning-call",
    "name": "continue_after_reasoning",
    "args": {},
  },
]
ANSWER_START = "正文流开始\n\n" + "\n\n".join(
  f"正文段落 {index}：" + "真实运行中的正文流式预览。" * 8 for index in range(12)
)
ANSWER_DELTAS = [f"\n\n正文增量 {index}：持续更新。" for index in range(8)]
ANSWER_END = "\n\n正文流完成"
ANSWER = ANSWER_START + "".join(ANSWER_DELTAS) + ANSWER_END
SAVED_ANSWER_CONTENT = [{"type": "text", "text": ANSWER, "index": 0}]


async def wait_for_marker(name):
  while not Path(name).exists():
    await asyncio.sleep(0.05)


class ReasoningModel(ToolModel):
  async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
    response = self.responses[self.i]
    self.i = (self.i + 1) % len(self.responses)
    yield ChatGenerationChunk(
      message=AIMessageChunk(content=response.content, tool_calls=response.tool_calls)
    )
    if response.tool_calls:
      return
    # The previous model message has already become a persisted root fact. This
    # model invocation emits normal content deltas, never a fabricated reasoning
    # delta. Markers let the real WebView pause and inspect each execution phase.
    Path("reasoning-answer-started").touch()
    await wait_for_marker("allow-reasoning-update")
    for delta in ANSWER_DELTAS:
      yield ChatGenerationChunk(message=AIMessageChunk(content=delta))
      await asyncio.sleep(0.03)
    Path("reasoning-answer-updated").touch()
    await wait_for_marker("allow-reasoning-completion")
    yield ChatGenerationChunk(message=AIMessageChunk(content=ANSWER_END))


@tool
def continue_after_reasoning() -> str:
  """Continue a deterministic run after its reasoning message is committed."""
  return "推理事实已保存，继续生成正文。"


async def create_reasoning_agent(*, config, middlewares, checkpointer, tool_registry):
  return create_agent(
    ReasoningModel(
      responses=[
        AIMessage(
          content=MODEL_CONTENT,
          tool_calls=[
            {"id": "reasoning-call", "name": "continue_after_reasoning", "args": {}}
          ],
        ),
        AIMessage(content=ANSWER_START),
      ]
    ),
    tools=[continue_after_reasoning],
    middleware=middlewares,
    context_schema=AgentRunContext,
    checkpointer=checkpointer,
  )
