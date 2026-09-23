import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from langchain.agents import create_agent
from langchain_core.messages import AIMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from pydantic import ValidationError
from runtime_fixtures import ToolModel
from shikigen.app_config import AppConfig, McpConfig, ModelConfig
from shikigen.contracts.events import ApprovalSubmission
from shikigen.contracts.runs import (
  ApprovalConflict,
  InvalidApprovalResponse,
  InvalidRunState,
)
from shikigen.core.approval import build_approval_middleware
from shikigen.core.execution import ExecutionOutcome, ExecutionReason
from shikigen.persistence import ChatStore
from shikigen.runtime.composition import assemble_runtime
from shikigen.runtime.runs import RunTransitions
from sse_fixtures import parse_sse_frames
from test_approval_pause import nested_graph

from app.run_contract import SSE_EVENT
from app.server import app


class ApprovalResumeTests(unittest.IsolatedAsyncioTestCase):
  async def asyncSetUp(self):
    directory = tempfile.TemporaryDirectory()
    self.addCleanup(directory.cleanup)
    self.path = Path(directory.name) / "product.db"
    self.store = await ChatStore.open(self.path)
    self.addAsyncCleanup(self.store.close)
    self.calls = []

    @tool
    def write_file(path: str) -> str:
      """Write a file."""
      self.calls.append(path)
      return "written"

    @tool
    def bash(command: str) -> str:
      """Run a command."""
      self.calls.append(command)
      return "done"

    self.agent = create_agent(
      ToolModel(
        responses=[
          AIMessage(
            id="ai-1",
            content="",
            tool_calls=[
              {"id": "write-1", "name": "write_file", "args": {"path": "a.txt"}},
              {"id": "bash-1", "name": "bash", "args": {"command": "first"}},
              {"id": "bash-repeat", "name": "bash", "args": {"command": "first-again"}},
            ],
          ),
          AIMessage(
            id="ai-2",
            content="",
            tool_calls=[
              {"id": "bash-2", "name": "bash", "args": {"command": "second"}},
            ],
          ),
          AIMessage(id="ai-3", content="done"),
        ]
      ),
      tools=[write_file, bash],
      middleware=[build_approval_middleware(["write_file", "bash"])],
      checkpointer=InMemorySaver(),
    )
    self.runtime = self.make_runtime(self.agent, self.store)
    self.thread = await self.runtime.threads.create_thread()
    self.first = await self.runtime.runs.start_run(self.thread, "do work")
    self.run_id = self.first.run_id
    self.assertEqual(
      (await self.runtime.runs.wait_run(self.first))["status"], "interrupted"
    )

  def make_runtime(self, agent, store):
    runtime = assemble_runtime(
      config=AppConfig(model=ModelConfig(), mcp=McpConfig()),
      agent=agent,
      chat_store=store,
    )
    self.addAsyncCleanup(runtime.lifecycle.shutdown)
    return runtime

  async def facts(self):
    return await self.store.list_run_events(self.thread, self.run_id)

  async def responses(self):
    required = next(
      e for e in reversed(await self.facts()) if e["event_type"] == "approval_required"
    )
    return {
      item["id"]: {
        "decisions": [{"type": "approve"} for _ in item["value"]["action_requests"]]
      }
      for item in required["content"]["interrupts"]
    }

  async def test_two_pauses_concurrent_response_and_exact_resume(self):
    responses = await self.responses()
    first_pending = (await self.facts())[-2]["content"]
    with patch.object(
      self.agent, "astream_events", wraps=self.agent.astream_events
    ) as calls:
      results = await asyncio.gather(
        self.runtime.runs.resume_run(self.thread, self.run_id, responses),
        self.runtime.runs.resume_run(self.thread, self.run_id, responses),
        return_exceptions=True,
      )
      successes = [r for r in results if not isinstance(r, Exception)]
      self.assertEqual(len(successes), 1)
      self.assertEqual(sum(isinstance(r, ApprovalConflict) for r in results), 1)
      resumed = successes[0]
      self.assertEqual(
        (await self.runtime.runs.wait_run(resumed))["status"], "interrupted"
      )
      self.assertEqual(calls.call_count, 1)
      self.assertIsInstance(calls.call_args.args[0], Command)
      self.assertEqual(
        calls.call_args.kwargs["config"]["configurable"],
        first_pending["checkpoint"]["configurable"],
      )
    self.assertEqual(resumed.run_id, self.run_id)
    self.assertCountEqual(self.calls, ["a.txt", "first", "first-again"])
    with self.assertRaises(ApprovalConflict):
      await self.runtime.runs.resume_run(self.thread, self.run_id, responses)
    second = await self.responses()
    self.assertTrue(set(second).isdisjoint(responses))
    # 第二轮 reject 不执行工具，但会把拒绝结果交回 Graph。
    second[next(iter(second))]["decisions"] = [
      {"type": "reject", "message": "do not run"}
    ]
    final = await self.runtime.runs.resume_run(self.thread, self.run_id, second)
    self.assertEqual((await self.runtime.runs.wait_run(final))["status"], "completed")
    self.assertCountEqual(self.calls, ["a.txt", "first", "first-again"])
    facts = await self.facts()
    self.assertEqual(
      len([e for e in facts if e["event_type"] == "approval_resolved"]), 2
    )
    self.assertEqual(len([e for e in facts if e["event_type"] == "run_running"]), 3)
    messages = [e for e in facts if e["category"] == "message"]
    self.assertEqual(len({e["event_key"] for e in messages}), len(messages))
    self.assertEqual(
      len([e for e in messages if e["event_type"] == "human_message"]), 1
    )
    live = [
      e.data async for e in final.stream.subscribe() if e.event == "durable_event"
    ]
    self.assertEqual(live, [e for e in facts if e["seq"] >= final.replay_start_seq])
    observation = await self.runtime.runs.observe_run(self.thread, self.run_id)
    self.assertEqual(
      [e.data async for e in observation if e.event == "durable_event"], facts
    )
    with self.assertRaises(InvalidRunState):
      await RunTransitions(self.store).settle_execution(
        thread_id=self.thread,
        run_id=self.run_id,
        invocation_seq=1,
        outcome=ExecutionOutcome(ExecutionReason.COMPLETED),
      )

  async def test_invalid_responses_leave_pending_unchanged(self):
    before = await self.facts()
    responses = await self.responses()
    identity = next(iter(responses))
    with self.assertRaises(InvalidApprovalResponse):
      await self.runtime.runs.resume_run(
        self.thread, self.run_id, {identity: {"decisions": [{"type": "approve"}]}}
      )
    for decision in (
      {"type": "edit"},
      {"type": "respond"},
      {"type": "approve", "message": "extra"},
    ):
      with self.assertRaises(ValidationError):
        await self.runtime.runs.resume_run(
          self.thread, self.run_id, {identity: {"decisions": [decision, decision]}}
        )
    with self.assertRaises(ApprovalConflict):
      await self.runtime.runs.resume_run(
        self.thread, self.run_id, {"old": responses[identity]}
      )
    with patch.object(self.agent, "aget_state", side_effect=OSError("unavailable")):
      with self.assertRaises(InvalidRunState):
        await self.runtime.runs.resume_run(self.thread, self.run_id, responses)
    self.assertEqual(await self.facts(), before)
    self.assertEqual(self.calls, [])

  async def test_acceptance_rollback_and_cross_connection_competition(self):
    submission = ApprovalSubmission(responses=await self.responses())
    before = await self.facts()
    original = self.store._events.insert_fact

    async def fail(*args):
      if args[2] == "run_running":
        raise OSError("disk failed")
      await original(*args)

    with patch.object(self.store._events, "insert_fact", side_effect=fail):
      with self.assertRaises(OSError):
        await RunTransitions(self.store).accept_approval_decisions(
          thread_id=self.thread, run_id=self.run_id, submission=submission
        )
    self.assertEqual(await self.facts(), before)
    self.assertEqual(
      (await self.store.get_run(self.run_id, self.thread))["status"], "interrupted"
    )
    other = await ChatStore.open(self.path)
    self.addAsyncCleanup(other.close)
    results = await asyncio.gather(
      *[
        RunTransitions(store).accept_approval_decisions(
          thread_id=self.thread, run_id=self.run_id, submission=submission
        )
        for store in (self.store, other)
      ],
      return_exceptions=True,
    )
    self.assertEqual(sum(isinstance(r, ApprovalConflict) for r in results), 1)
    self.assertEqual(
      len([e for e in await self.facts() if e["event_type"] == "approval_resolved"]), 1
    )
    self.assertEqual(self.calls, [])  # 接受事务本身不执行 Graph。

  async def test_waits_for_previous_cleanup_and_survives_caller_cancellation(self):
    # 下一次暂停已经提交，但旧 invocation 仍在发布/清理。
    settled, release = asyncio.Event(), asyncio.Event()
    original = self.runtime.runs._transitions.settle_execution

    async def settle(**kwargs):
      result = await original(**kwargs)
      settled.set()
      await release.wait()
      return result

    with patch.object(
      self.runtime.runs._transitions, "settle_execution", side_effect=settle
    ):
      second = await self.runtime.runs.resume_run(
        self.thread, self.run_id, await self.responses()
      )
      await asyncio.wait_for(settled.wait(), 3)
      caller = asyncio.create_task(
        self.runtime.runs.resume_run(self.thread, self.run_id, await self.responses())
      )
      await asyncio.sleep(0.02)
      self.assertFalse(caller.done())
      self.assertIs(self.runtime.executions.get(self.thread, self.run_id), second)
      caller.cancel()
      with self.assertRaises(asyncio.CancelledError):
        await caller
      release.set()
      await self.runtime.runs.wait_run(second)
      for _ in range(200):
        row = await self.runtime.runs.read_run(self.thread, self.run_id)
        if row["status"] == "completed":
          break
        await asyncio.sleep(0.01)
      self.assertEqual(row["status"], "completed")
      self.assertCountEqual(self.calls, ["a.txt", "first", "first-again", "second"])

  async def test_start_failure_preserves_resolved_fact(self):
    with patch(
      "shikigen.runtime.runs.start_run_execution",
      side_effect=RuntimeError("cannot start"),
    ):
      with self.assertRaisesRegex(RuntimeError, "cannot start"):
        await self.runtime.runs.resume_run(
          self.thread, self.run_id, await self.responses()
        )
    run = await self.runtime.runs.read_run(self.thread, self.run_id)
    self.assertEqual(run["status"], "error")
    self.assertEqual(run["error_code"], "resume_start_failed")
    self.assertEqual(
      len([e for e in await self.facts() if e["event_type"] == "approval_resolved"]), 1
    )
    self.assertEqual(self.calls, [])

  async def test_http_submission_conflicts_and_rebuild(self):
    body = {"responses": await self.responses()}
    with patch.object(app.state, "runtime", self.runtime, create=True):
      async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
      ) as client:
        url = f"/api/threads/{self.thread}/runs/{self.run_id}/approval-decisions"
        wrong = await client.post(url.replace(self.thread, "wrong"), json=body)
        self.assertEqual(wrong.status_code, 404)
        invalid = await client.post(
          url, json={"responses": {"x": {"decisions": [{"type": "edit"}]}}}
        )
        self.assertEqual(invalid.status_code, 422)
        response = await client.post(url, json=body)
        self.assertEqual(response.status_code, 200)
        frames = parse_sse_frames(response.text)
        for frame in frames:
          SSE_EVENT.validate_python(frame)
        self.assertTrue(
          any(
            f["event"] == "event" and f["data"]["event_type"] == "resolved"
            for f in frames
          )
        )
        again = await client.post(url, json=body)
        self.assertEqual(again.status_code, 409)
        current = await client.get(again.json()["detail"]["stream"])
        self.assertEqual(current.status_code, 200)
        self.assertIn('"event_type":"required"', current.text)

  async def test_nested_interrupts_resume_together(self):
    runtime = self.make_runtime(nested_graph(), self.store)
    thread = await runtime.threads.create_thread()
    first = await runtime.runs.start_run(thread, "nested")
    await runtime.runs.wait_run(first)
    pending = (await runtime.runs.list_run_events(thread, first.run_id))[-2]["content"][
      "interrupts"
    ]
    responses = {p["id"]: {"decisions": [{"type": "approve"}]} for p in pending}
    self.assertEqual(len(responses), 2)
    with self.assertRaises(ApprovalConflict):
      await runtime.runs.resume_run(
        thread, first.run_id, {pending[0]["id"]: responses[pending[0]["id"]]}
      )
    resumed = await runtime.runs.resume_run(thread, first.run_id, responses)
    self.assertEqual((await runtime.runs.wait_run(resumed))["status"], "completed")

  async def test_observe_active_resume_combines_history_and_current_cache_once(self):
    entered, release = asyncio.Event(), asyncio.Event()
    original = self.store.append_committed_event

    async def append(**kwargs):
      if kwargs["event_type"] == "tool_message":
        entered.set()
        await release.wait()
      return await original(**kwargs)

    with patch.object(self.store, "append_committed_event", side_effect=append):
      resumed = await self.runtime.runs.resume_run(
        self.thread, self.run_id, await self.responses()
      )
      try:
        await asyncio.wait_for(entered.wait(), 3)
        observation = await self.runtime.runs.observe_run(self.thread, self.run_id)
        self.assertEqual(observation.run["status"], "running")
      finally:
        release.set()
      seen = [e.data async for e in observation if e.event == "durable_event"]
      await self.runtime.runs.wait_run(resumed)
    self.assertEqual(seen, await self.facts())
    self.assertEqual(len({e["seq"] for e in seen}), len(seen))

  async def test_disallowed_decision_does_not_consume_pending(self):
    from shikigen.contracts.events import ApprovalRequired
    from shikigen.core.approval import validate_responses

    required = ApprovalRequired.model_validate((await self.facts())[-2]["content"])
    # 自定义策略可只允许批准；模型字段允许 reject 不代表该动作允许拒绝。
    required.interrupts[0].value["review_configs"][0]["allowed_decisions"] = ["approve"]
    responses = await self.responses()
    responses[next(iter(responses))]["decisions"][0] = {"type": "reject"}
    with self.assertRaises(InvalidApprovalResponse):
      validate_responses(required, ApprovalSubmission(responses=responses))
