"""崩溃同步点在实际事务、提交后广播和工具节点内；禁止 HTTP 依赖。"""

import asyncio
import importlib.abc
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch


class NoHttp(importlib.abc.MetaPathFinder):
  def find_spec(self, fullname, path=None, target=None):
    if fullname.split(".")[0] in {"app", "fastapi"}:
      raise AssertionError(f"HTTP dependency imported: {fullname}")


sys.meta_path.insert(0, NoHttp())

from langchain_core.messages import AIMessage  # noqa: E402
from langgraph.graph import END, START, MessagesState, StateGraph  # noqa: E402
from langgraph.types import interrupt  # noqa: E402
from shikigen.app_config import AppConfig, McpConfig, ModelConfig  # noqa: E402
from shikigen.runtime.composition import open_runtime  # noqa: E402
from shikigen.runtime.run_events import RunEventIngestor  # noqa: E402


async def main():
  directory = Path(sys.argv[1])
  phase = sys.argv[2]
  database = directory / "runtime.db"
  config = AppConfig(
    model=ModelConfig(),
    mcp=McpConfig(),
    database={"path": str(database)},
    checkpointer={"type": "sqlite", "path": str(database)},
  )

  async def factory(*, checkpointer, **kwargs):
    def node(state):
      interrupt(
        {
          "action_requests": [{"name": "demo", "args": {}, "description": "review"}],
          "review_configs": [{"action_name": "demo", "allowed_decisions": ["approve"]}],
        }
      )
      # 代表已发生的外部副作用；恢复扫描不能再次执行。
      with (directory / "effects").open("a") as output:
        output.write("effect\n")
        output.flush()
        os.fsync(output.fileno())
      if phase == "resumed":
        os._exit(73)
      return {"messages": [AIMessage(id="done", content="done")]}

    graph = StateGraph(MessagesState)
    graph.add_node("work", node)
    graph.add_edge(START, "work")
    graph.add_edge("work", END)
    return graph.compile(checkpointer=checkpointer)

  with patch("shikigen.runtime.composition.create_lead_agent", new=factory):
    async with open_runtime(config) as runtime:
      if phase == "inspect":
        thread, run_id = json.loads((directory / "identity").read_text())
        run = await runtime.runs.read_run(thread, run_id)
        facts = await runtime.runs.list_run_events(thread, run_id)
        observation = await runtime.runs.observe_run(thread, run_id)
        assert [e.data async for e in observation] == facts
        print(json.dumps({"run": run, "facts": facts}), flush=True)
        return
      thread = await runtime.threads.create_thread()
      if phase in {"created", "create_uncommitted"}:

        async def stop(*args, **kwargs):
          os._exit(73)

        if phase == "created":

          def stop_start(**kwargs):
            (directory / "identity").write_text(json.dumps([thread, kwargs["run_id"]]))
            os._exit(73)

          with patch("shikigen.runtime.runs.start_run_execution", new=stop_start):
            await runtime.runs.start_run(thread, "start")
        else:
          original = runtime.chat_store._events.insert_fact

          async def uncommitted(*args):
            await original(*args)
            (directory / "identity").write_text(json.dumps([thread, args[1]]))
            os._exit(73)

          with patch.object(runtime.chat_store._events, "insert_fact", new=uncommitted):
            await runtime.runs.start_run(thread, "start")
      execution = await runtime.runs.start_run(thread, "start")
      assert (await runtime.runs.wait_run(execution))["status"] == "interrupted"
      (directory / "identity").write_text(json.dumps([thread, execution.run_id]))
      facts = await runtime.runs.list_run_events(thread, execution.run_id)
      required = next(e for e in facts if e["event_type"] == "approval_required")
      responses = {
        item["id"]: {"decisions": [{"type": "approve"}]}
        for item in required["content"]["interrupts"]
      }
      if phase == "paused":
        os._exit(73)
      if phase == "corrupt":
        # 成功读取但指定 checkpoint 已经不存在，是永久不一致。
        connection = runtime.chat_store._connection
        await connection.execute("DELETE FROM checkpoints")
        await connection.commit()
        os._exit(73)
      if phase == "approval_uncommitted":
        original = runtime.chat_store._events.insert_fact

        async def uncommitted_approval(*args):
          await original(*args)
          if args[2] == "approval_resolved":
            os._exit(73)

        with patch.object(
          runtime.chat_store._events, "insert_fact", new=uncommitted_approval
        ):
          await runtime.runs.resume_run(thread, execution.run_id, responses)
      if phase == "accepted":

        def stop_resume(**kwargs):
          os._exit(73)

        with patch("shikigen.runtime.runs.start_run_execution", new=stop_resume):
          await runtime.runs.resume_run(thread, execution.run_id, responses)
      if phase == "completed":
        original_publish = RunEventIngestor.publish

        def stop_publish(*args, **kwargs):
          settlement = kwargs.get("settlement")
          if settlement is not None and settlement.status == "completed":
            os._exit(73)
          return original_publish(*args, **kwargs)

        with patch.object(RunEventIngestor, "publish", new=staticmethod(stop_publish)):
          resumed = await runtime.runs.resume_run(thread, execution.run_id, responses)
          await runtime.runs.wait_run(resumed)
      if phase == "resumed":
        resumed = await runtime.runs.resume_run(thread, execution.run_id, responses)
        await runtime.runs.wait_run(resumed)
      raise AssertionError(f"Missing crash point: {phase}")


asyncio.run(main())
