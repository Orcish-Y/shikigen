"""第 07 票实机正文夹具：使用真实消息 middleware、HTTP、SSE，不访问模型网络。"""

from langchain.agents import create_agent
from langchain_core.messages import AIMessage
from langchain_core.tools import tool
from runtime_fixtures import ToolModel
from shikigen.core.context import AgentRunContext

CODE = "  start = 1\n\n" + "\n".join(f"value_{i} = {i}" for i in range(90))
TOOL_TEXT = "  **工具原文**\n# 不渲染标题\n"
MARKDOWN = (
  "# Agent 正文标题\n\n**粗体正文**\n\n"
  "<script>window.__injected = true</script>\n\n"
  "- [x] 只读任务\n\n"
  "| 长表格 | 值 |\n| --- | --- |\n| " + "宽内容" * 70 + " | 1 |\n\n"
  '```python filename="scripts/main.py"\n' + CODE + "\n```\n\n"
  "说明[^1]\n\n[^1]: 最终脚注\n\n"
  "[网页](https://example.org/test)\n\n"
  "[报告](C:\\work\\reports\\one.pdf)\n\n"
  "![网页图片](https://example.org/not-loaded.png)\n"
)
CONTENT = [
  {"type": "text", "text": MARKDOWN, "source": {"fixture": 7}},
  {"type": "unknown", "text": "未知块保持 JSON", "values": [0, False, None]},
  {"type": "text", "text": "## 数组最后一块"},
]


@tool
def markdown_echo() -> str:
  """Return literal tool text for reading."""
  return TOOL_TEXT


async def markdown_agent(*, config, middlewares, checkpointer, tool_registry):
  model = ToolModel(
    responses=[
      AIMessage(
        content="首条脚注[^1]\n\n[^1]: 首条脚注内容",
        tool_calls=[{"id": "markdown-call", "name": "markdown_echo", "args": {}}],
      ),
      AIMessage(content=CONTENT),
    ]
  )
  return create_agent(
    model,
    tools=[markdown_echo],
    middleware=middlewares,
    context_schema=AgentRunContext,
    checkpointer=checkpointer,
  )
