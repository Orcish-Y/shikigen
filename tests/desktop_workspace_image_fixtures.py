"""实际 Graph 的本地图片与长正文夹具，无模型网络或工具写入。"""

from pathlib import Path

from langchain.agents import create_agent
from langchain_core.messages import AIMessage
from runtime_fixtures import ToolModel
from shikigen.core.context import AgentRunContext


async def workspace_image_agent(*, config, middlewares, checkpointer, tool_registry):
  absolute_image = Path(config.workspace_root) / "images/tall.png"
  markdown = (
    "# 工作目录图片\n\n![长图片](images/tall.png)\n\n"
    + "\n\n".join(
      f"阅读段落 {index}：" + "保持正在阅读的正文位置。" * 10 for index in range(45)
    )
    + "\n\n![重复引用](images/tall.png)\n\n"
    + f"![绝对引用](<{absolute_image}>)\n\n"
    + "![安全 SVG](images/inert.svg)\n\n"
    + "![缺失图片](images/missing.png)\n\n"
    + "![越界图片](../outside.png)\n\n"
    + "![网页图片](https://example.org/never-load.png)\n\n"
    + "[报告](notes/report.txt)\n\n"
    + "```text\n![代码原文](images/code-only.png)\n```\n\n图片正文结束"
  )
  return create_agent(
    ToolModel(
      responses=[
        AIMessage(
          content=[
            {"type": "text", "text": markdown},
            {"type": "unknown", "path": "images/json-only.png"},
          ]
        )
      ]
    ),
    middleware=middlewares,
    context_schema=AgentRunContext,
    checkpointer=checkpointer,
  )
