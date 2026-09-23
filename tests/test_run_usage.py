import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from runtime_fixtures import ToolModel
from shikigen.app_config import AppConfig, McpConfig, ModelConfig
from shikigen.contracts.runs import InvalidRunState
from shikigen.core.approval import build_approval_middleware
from shikigen.core.execution import ExecutionOutcome, ExecutionReason
from shikigen.middleware.goal_middleware import GoalEvaluator, GoalMiddleware
from shikigen.persistence import ChatStore
from shikigen.runtime.composition import assemble_runtime
from shikigen.runtime.runs import RunTransitions
from shikigen.tools import ToolRegistry, build_task_tool


def reply(text="done", **kwargs):
  return AIMessage(
    content=text,
    usage_metadata={
      "input_tokens": 7,
      "output_tokens": 3,
      "total_tokens": 10,
    },
    **kwargs,
  )


def usage(n=1):
  return {
    "total_input": 7 * n,
    "total_output": 3 * n,
    "total_tokens": 10 * n,
    "calls": n,
    "by_model": {"demo": {"input": 7 * n, "output": 3 * n, "calls": n}},
  }


class RunUsageTests(unittest.IsolatedAsyncioTestCase):
  async def asyncSetUp(self):
    directory = tempfile.TemporaryDirectory()
    self.addCleanup(directory.cleanup)
    self.store = await ChatStore.open(Path(directory.name) / "db")
    self.addAsyncCleanup(self.store.close)
    await self.store.create_thread("t")

  def runtime(self, agent):
    runtime = assemble_runtime(
      config=AppConfig(model=ModelConfig(), mcp=McpConfig()),
      agent=agent,
      chat_store=self.store,
    )
    self.addAsyncCleanup(runtime.lifecycle.shutdown)
    return runtime

  async def test_callbacks_include_parent_child_and_goal_once(self):
    child = ToolModel(responses=[reply("child")])
    task = build_task_tool(child, ToolRegistry())
    parent = ToolModel(
      responses=[
        reply(
          "",
          tool_calls=[
            {
              "id": "c",
              "name": "task",
              "args": {"description": "work"},
            }
          ],
        ),
        reply(),
      ]
    )
    evaluator = GoalEvaluator(ToolModel(responses=[reply("YES done")]))
    agent = create_agent(parent, tools=[task], middleware=[GoalMiddleware(evaluator)])
    runtime = self.runtime(agent)
    execution = await runtime.runs.start_run("t", "/goal work")
    result = await runtime.runs.wait_run(execution)
    self.assertEqual(result["usage"]["calls"], 4)
    self.assertEqual(result["usage"]["total_tokens"], 40)
    self.assertFalse(result["usage_pending"])
    events = [e async for e in execution.stream.subscribe()]
    usages = [e for e in events if e.event == "usage"]
    self.assertEqual(len(usages), 1)
    self.assertEqual(usages[0].data, result["usage"])
    self.assertLess(
      events.index(usages[0]),
      next(
        i
        for i, e in enumerate(events)
        if e.event == "durable_event" and e.data["event_type"] == "run_completed"
      ),
    )

  async def test_pause_resume_totals_visible_before_notifications(self):
    @tool
    def write_file() -> str:
      """Write a file."""
      return "ok"

    agent = create_agent(
      ToolModel(
        responses=[
          reply("", tool_calls=[{"id": "c", "name": "write_file", "args": {}}]),
          reply(),
        ]
      ),
      tools=[write_file],
      middleware=[build_approval_middleware(["write_file", "bash"])],
      checkpointer=InMemorySaver(),
    )
    runtime = self.runtime(agent)
    first = await runtime.runs.start_run("t", "work")
    result = await runtime.runs.wait_run(first)
    self.assertEqual(result["usage"]["total_tokens"], 10)
    self.assertFalse(result["usage_pending"])
    facts = await runtime.runs.list_run_events("t", first.run_id)
    responses = {
      i["id"]: {"decisions": [{"type": "approve"}]}
      for i in facts[-2]["content"]["interrupts"]
    }
    resumed = await runtime.runs.resume_run("t", first.run_id, responses)
    async for event in resumed.stream.subscribe():
      if event.event == "durable_event" and event.data["event_type"] == "run_completed":
        result = await runtime.runs.read_run("t", first.run_id)
        self.assertEqual(result["usage"]["total_tokens"], 20)
        self.assertFalse(result["usage_pending"])
    self.assertEqual((await runtime.runs.wait_run(resumed))["usage"]["calls"], 2)

  async def create(self):
    return await RunTransitions(self.store).create_run(
      thread_id="t", run_id="r", entry_message=HumanMessage(id="h", content="hi")
    )

  async def test_idempotent_settlement_and_conflicting_retry(self):
    created = await self.create()
    self.assertIsNone(created.run["usage"])
    self.assertTrue(created.run["usage_pending"])
    args = dict(
      thread_id="t",
      run_id="r",
      invocation_seq=created.events[0]["seq"],
      outcome=ExecutionOutcome(ExecutionReason.COMPLETED),
      usage=usage(),
    )
    first = await RunTransitions(self.store).settle_execution(**args)
    await RunTransitions(self.store).settle_execution(**args)
    self.assertEqual((await self.store.get_run("r", "t"))["usage"], usage())
    self.assertEqual(first.usage, usage())
    with self.assertRaises(InvalidRunState):
      await RunTransitions(self.store).settle_execution(**(args | {"usage": usage(2)}))

  async def test_usage_and_status_roll_back_together(self):
    await self.create()

    async def fail(*args):
      raise OSError("disk failed")

    with patch.object(self.store._events, "insert_fact", side_effect=fail):
      with self.assertRaises(OSError):
        await RunTransitions(self.store).settle_execution(
          thread_id="t",
          run_id="r",
          usage=usage(),
          outcome=ExecutionOutcome(ExecutionReason.COMPLETED),
        )
    result = await self.store.get_run("r", "t")
    self.assertIsNone(result["usage"])
    self.assertTrue(result["usage_pending"])
    self.assertEqual(result["status"], "running")

  async def test_cancel_commits_before_cleanup_then_known_usage_arrives(self):
    entered, release = asyncio.Event(), asyncio.Event()

    async def loop(*args, execution, token_tracker, **kwargs):
      await token_tracker.on_llm_end(
        SimpleNamespace(
          generations=[],
          llm_output={
            "model_name": "demo",
            "token_usage": {"prompt_tokens": 7, "completion_tokens": 3},
          },
        )
      )
      entered.set()
      await execution.abort_event.wait()
      await release.wait()
      return ExecutionOutcome(ExecutionReason.ABORTED)

    runtime = self.runtime(None)
    with patch("shikigen.runtime.run_execution.execute_agent_loop", side_effect=loop):
      execution = await runtime.runs.start_run("t", "work")
      await entered.wait()
      cancelled = await runtime.runs.cancel_run("t", execution.run_id)
      self.assertTrue(cancelled["usage_pending"])
      self.assertIsNone(cancelled["usage"])
      release.set()
      result = await runtime.runs.wait_run(execution)
    self.assertEqual(result["status"], "cancelled")
    self.assertEqual(result["usage"], usage())
    self.assertFalse(result["usage_pending"])

  async def test_error_keeps_reported_usage(self):
    async def loop(*args, token_tracker, **kwargs):
      await token_tracker.on_llm_end(
        SimpleNamespace(
          generations=[],
          llm_output={"token_usage": {"prompt_tokens": 7, "completion_tokens": 3}},
        )
      )
      return ExecutionOutcome(
        ExecutionReason.FAILED, error=RuntimeError("model failed")
      )

    runtime = self.runtime(None)
    with patch("shikigen.runtime.run_execution.execute_agent_loop", side_effect=loop):
      execution = await runtime.runs.start_run("t", "work")
      result = await runtime.runs.wait_run(execution)
    self.assertEqual(result["status"], "error")
    self.assertEqual(result["usage"]["total_tokens"], 10)
    self.assertFalse(result["usage_pending"])

  async def test_observation_metadata_exposes_persisted_usage(self):
    from sse_fixtures import parse_sse_frames

    from app.routes.run import stream_observation
    from app.run_contract import SSE_EVENT

    runtime = self.runtime(create_agent(ToolModel(responses=[reply()]), tools=[]))
    execution = await runtime.runs.start_run("t", "work")
    result = await runtime.runs.wait_run(execution)
    observation = await runtime.runs.observe_run("t", execution.run_id)
    frames = parse_sse_frames(
      "".join([f async for f in stream_observation(observation)])
    )
    metadata = SSE_EVENT.validate_python(frames[0]).data
    self.assertEqual(metadata.usage.total_tokens, result["usage"]["total_tokens"])
    self.assertFalse(metadata.usage_pending)

  async def test_storage_failure_is_observable_without_false_completion(self):
    runtime = self.runtime(create_agent(ToolModel(responses=[reply()]), tools=[]))
    with patch.object(
      runtime.runs._transitions, "settle_execution", side_effect=OSError("disk failed")
    ):
      with self.assertLogs("shikigen.runtime.run_execution", level="ERROR") as logs:
        execution = await runtime.runs.start_run("t", "work")
        with self.assertRaises(OSError):
          await runtime.runs.wait_run(execution)
        await asyncio.sleep(0)
    self.assertIn(execution.run_id, "\n".join(logs.output))
    events = [e async for e in execution.stream.subscribe()]
    self.assertFalse(any(e.event == "usage" for e in events))
    self.assertEqual(events[-1].data["code"], "run_persistence_failed")
    result = await runtime.runs.read_run("t", execution.run_id)
    self.assertIsNone(result["usage"])
    self.assertTrue(result["usage_pending"])
    self.assertEqual(result["status"], "running")

  async def test_shutdown_does_not_turn_unsettled_usage_into_zero(self):
    entered = asyncio.Event()

    async def loop(*args, **kwargs):
      entered.set()
      await asyncio.Event().wait()

    runtime = self.runtime(None)
    with patch("shikigen.runtime.run_execution.execute_agent_loop", side_effect=loop):
      execution = await runtime.runs.start_run("t", "work")
      await entered.wait()
      await runtime.executions.shutdown()
    result = await runtime.runs.read_run("t", execution.run_id)
    self.assertIsNone(result["usage"])
    self.assertTrue(result["usage_pending"])
