"""由 test_runtime 在独立进程中运行，先阻断 HTTP 导入，再装配真实资源。"""

import asyncio
import importlib.abc
import sys
from pathlib import Path


class NoHttp(importlib.abc.MetaPathFinder):
  def find_spec(self, fullname, path=None, target=None):
    if any(
      fullname == name or fullname.startswith(name + ".")
      for name in ("fastapi", "app.server", "app.routes")
    ):
      raise AssertionError(f"HTTP dependency imported: {fullname}")


sys.meta_path.insert(0, NoHttp())
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime_fixtures import deterministic_agent  # noqa: E402
from shikigen.app_config import AppConfig, McpConfig, ModelConfig  # noqa: E402

from app.composition import open_runtime  # noqa: E402


async def main():
  path = sys.argv[1]
  config = AppConfig(
    model=ModelConfig(),
    mcp=McpConfig(),
    database={"path": path},
    checkpointer={"type": "sqlite", "path": path},
  )
  async with open_runtime(config, agent_factory=deterministic_agent) as runtime:
    thread = await runtime.threads.create_thread()
    execution = await runtime.runs.start_run(thread, "1 + 2")
    subscription = execution.stream.subscribe()
    await subscription.aclose()
    result = await runtime.runs.wait_run(execution)
    assert result["status"] == "completed", result
    messages = await runtime.runs.list_run_messages(thread, execution.run_id)
    assert [m["content"]["type"] for m in messages] == ["human", "ai", "tool", "ai"]
    assert messages[-1]["content"]["content"] == "3"
    assert runtime.executions.get(thread, execution.run_id) is None
  async with open_runtime(config, agent_factory=deterministic_agent) as runtime:
    assert await runtime.runs.read_run(thread, execution.run_id) == result
    assert await runtime.runs.list_run_messages(thread, execution.run_id) == messages
  assert not any(
    name in sys.modules for name in ("fastapi", "app.server", "app.routes")
  )
  print("NO_HTTP_RUNTIME_OK")


if __name__ == "__main__":
  asyncio.run(main())
