"""由 test_runtime 在独立进程中运行，先阻断 HTTP 导入，再装配真实资源。"""

import asyncio
import importlib.abc
import sys
from pathlib import Path
from unittest.mock import patch


class NoHttp(importlib.abc.MetaPathFinder):
  def find_spec(self, fullname, path=None, target=None):
    if any(
      fullname == name or fullname.startswith(name + ".")
      for name in ("fastapi", "app.server", "app.routes")
    ):
      raise AssertionError(f"HTTP dependency imported: {fullname}")


sys.meta_path.insert(0, NoHttp())
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langchain_core.messages import AIMessage  # noqa: E402
from langgraph.graph import END, START, MessagesState, StateGraph  # noqa: E402
from langgraph.types import interrupt  # noqa: E402
from runtime_fixtures import deterministic_agent  # noqa: E402
from shikigen.app_config import AppConfig, McpConfig, ModelConfig  # noqa: E402

from app.composition import open_runtime  # noqa: E402


async def approval_agent(*, config, middlewares, checkpointer, tool_registry):
  def approve(state):
    response = interrupt(
      {
        "action_requests": [{"name": "demo", "args": {}, "description": "review"}],
        "review_configs": [{"action_name": "demo", "allowed_decisions": ["approve"]}],
      }
    )
    assert response == {"decisions": [{"type": "approve"}]}
    return {"messages": [AIMessage(id="approved", content="approved")]}

  graph = StateGraph(MessagesState)
  graph.add_node("approve", approve)
  graph.add_edge(START, "approve")
  graph.add_edge("approve", END)
  return graph.compile(checkpointer=checkpointer)


async def main():
  path = sys.argv[1]
  config = AppConfig(
    model=ModelConfig(),
    mcp=McpConfig(),
    database={"path": path},
    checkpointer={"type": "sqlite", "path": path},
  )
  with patch("app.composition.create_lead_agent", new=deterministic_agent):
    async with open_runtime(config) as runtime:
      thread = await runtime.threads.create_thread()
      execution = await runtime.runs.start_run(thread, "1 + 2")
      subscription = execution.stream.subscribe()
      await subscription.aclose()
      observation = await runtime.runs.observe_run(thread, execution.run_id)
      async for _ in observation:
        pass
      result = await runtime.runs.wait_run(execution)
      assert result["status"] == "completed", result
      assert result["usage"]["calls"] == 2, result
      assert result["usage_pending"] is False, result
      messages = await runtime.runs.list_run_messages(thread, execution.run_id)
      assert [m["content"]["type"] for m in messages] == ["human", "ai", "tool", "ai"]
      assert messages[-1]["content"]["content"] == "3"
      assert runtime.executions.get(thread, execution.run_id) is None
  with patch("app.composition.create_lead_agent", new=deterministic_agent):
    async with open_runtime(config) as runtime:
      observation = await runtime.runs.observe_run(thread, execution.run_id)
      facts = [event.data async for event in observation]
      assert facts == await runtime.runs.list_run_events(thread, execution.run_id)
      assert await runtime.runs.read_run(thread, execution.run_id) == result
      assert await runtime.runs.list_run_messages(thread, execution.run_id) == messages
  # 关闭全部资源后，重新装配相同 Graph，从 SQLite 中的准确暂停位置恢复。
  with patch("app.composition.create_lead_agent", new=approval_agent):
    async with open_runtime(config) as runtime:
      thread = await runtime.threads.create_thread()
      execution = await runtime.runs.start_run(thread, "approval")
      assert (await runtime.runs.wait_run(execution))["status"] == "interrupted"
      facts = await runtime.runs.list_run_events(thread, execution.run_id)
      pending = facts[-2]["content"]["interrupts"]
  with patch("app.composition.create_lead_agent", new=approval_agent):
    async with open_runtime(config) as runtime:
      resumed = await runtime.runs.resume_run(
        thread,
        execution.run_id,
        {item["id"]: {"decisions": [{"type": "approve"}]} for item in pending},
      )
      assert resumed.run_id == execution.run_id
      result = await runtime.runs.wait_run(resumed)
      assert result["status"] == "completed"
      assert result["usage"] is not None and not result["usage_pending"]
      messages = await runtime.runs.list_run_messages(thread, resumed.run_id)
      assert [e["content"]["content"] for e in messages] == ["approval", "approved"]
  with patch("app.composition.create_lead_agent", new=approval_agent):
    async with open_runtime(config) as runtime:
      thread = await runtime.threads.create_thread()
      paused = await runtime.runs.start_run(thread, "cancel approval")
      assert (await runtime.runs.wait_run(paused))["status"] == "interrupted"
      cancelled = await runtime.runs.cancel_run(thread, paused.run_id)
      assert cancelled["status"] == "cancelled"
      observation = await runtime.runs.observe_run(thread, paused.run_id)
      facts = [e.data async for e in observation]
      assert [e["event_type"] for e in facts[-2:]] == [
        "approval_invalidated",
        "run_cancelled",
      ]
  assert not any(
    name in sys.modules for name in ("fastapi", "app.server", "app.routes")
  )
  print("NO_HTTP_RUNTIME_OK")


if __name__ == "__main__":
  asyncio.run(main())
