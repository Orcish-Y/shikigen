"""第 12 票：真实多 Interrupt / 多动作审批与可控工具执行，不访问模型服务。"""

import asyncio
import os
from pathlib import Path
from typing import Annotated

from langchain_core.messages import AIMessage, AnyMessage
from langchain_core.tools import tool
from langgraph.graph import END, START, StateGraph, add_messages
from langgraph.types import interrupt
from typing_extensions import TypedDict


class ApprovalState(TypedDict):
  messages: Annotated[list[AnyMessage], add_messages]


def build_approval_request(prefix: str):
  return {
    "action_requests": [
      {
        "name": name,
        "args": {
          "label": f"{prefix}-{index}",
          "lines": [f"参数第 {line} 行：原文与顺序保留" for line in range(80)],
        },
        "description": f"核对 {prefix} 的第 {index + 1} 项操作",
      }
      for index, name in enumerate(("bash", "write_file"))
    ],
    "review_configs": [
      {
        "action_name": name,
        "allowed_decisions": ["edit"]
        if os.environ.get("DESKTOP_TEST_UNSUPPORTED_APPROVAL") and index == 1
        else ["approve", "reject"],
      }
      for index, name in enumerate(("bash", "write_file"))
    ],
  }


async def create_approval_workbench_agent(
  *, config, middlewares, checkpointer, tool_registry, workspace_root=None
):
  workspace = workspace_root or Path.cwd()

  @tool("bash")
  async def execute_approval_bash(label: str, lines: list[str]) -> str:
    """仅在收到批准后执行可控操作。"""
    (workspace / f"approval-executed-{label}").write_text(
      "\n".join(lines), encoding="utf-8"
    )
    while not (workspace / "allow-approval-tools").exists():
      await asyncio.sleep(0.05)
    return f"{label} 完成"

  @tool("write_file")
  async def execute_approval_write(label: str, lines: list[str]) -> str:
    """仅在收到批准后写入测试工作目录。"""
    return await execute_approval_bash.ainvoke({"label": label, "lines": lines})

  def create_approval_node(prefix):
    async def perform_actions(state):
      request = build_approval_request(prefix)
      response = interrupt(request)
      results = []
      for action, decision in zip(
        request["action_requests"], response["decisions"], strict=True
      ):
        if decision["type"] == "approve":
          action_tool = (
            execute_approval_bash
            if action["name"] == "bash"
            else execute_approval_write
          )
          results.append(await action_tool.ainvoke(action["args"]))
        else:
          results.append(
            f"{action['args']['label']} 已拒绝：{decision.get('message', '')}"
          )
      return {
        "messages": [AIMessage(id=f"approval-{prefix}", content="\n".join(results))]
      }

    return perform_actions

  child = StateGraph(ApprovalState)
  child.add_node("review", create_approval_node("child"))
  child.add_edge(START, "review")
  child.add_edge("review", END)
  graph = StateGraph(ApprovalState)
  graph.add_node("main", create_approval_node("main"))
  graph.add_node("nested", child.compile())
  for node in ("main", "nested"):
    graph.add_edge(START, node)
    graph.add_edge(node, END)
  return graph.compile(checkpointer=checkpointer)
