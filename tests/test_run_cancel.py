import asyncio
import unittest
from unittest.mock import patch

import httpx
import test_approval_resume as approval_tests
from shikigen.event_contract import ApprovalSubmission
from shikigen.execution import ExecutionOutcome, ExecutionReason
from shikigen.persistence import ChatStore
from shikigen.runtime.run_state import ApprovalConflict

from app.run_contract import RunSseEncoder
from app.server import app


class RunCancelTests(unittest.IsolatedAsyncioTestCase):
  asyncSetUp = approval_tests.ApprovalResumeTests.asyncSetUp
  make_runtime = approval_tests.ApprovalResumeTests.make_runtime
  facts = approval_tests.ApprovalResumeTests.facts
  responses = approval_tests.ApprovalResumeTests.responses

  async def test_paused_cancel_invalidates_and_is_idempotent(self):
    responses = await self.responses()
    before = await self.facts()
    result = await self.runtime.runs.cancel_run(self.thread, self.run_id)
    self.assertEqual(result["status"], "cancelled")
    self.assertIsNotNone(result["completed_at"])
    facts = await self.facts()
    self.assertEqual(
      [e["event_type"] for e in facts[len(before) :]],
      ["approval_invalidated", "run_cancelled"],
    )
    self.assertEqual(set(facts[-2]["content"]["interrupt_ids"]), set(responses))
    self.assertEqual(
      await self.runtime.runs.cancel_run(self.thread, self.run_id), result
    )
    self.assertEqual(await self.facts(), facts)
    with self.assertRaises(ApprovalConflict):
      await self.runtime.runs.resume_run(self.thread, self.run_id, responses)
    observation = await self.runtime.runs.observe_run(self.thread, self.run_id)
    encoder = RunSseEncoder(self.thread, self.run_id)
    frames = [encoder.encode(e) async for e in observation]
    self.assertTrue(any("invalidated" in f for f in frames if f))
    late = await self.store.settle_execution(
      thread_id=self.thread,
      run_id=self.run_id,
      outcome=ExecutionOutcome(ExecutionReason.COMPLETED),
    )
    self.assertEqual(late.status, "cancelled")
    self.assertEqual(await self.facts(), facts)

  async def test_cancel_transaction_rolls_back_both_facts(self):
    before = await self.facts()
    original = self.store._insert_fact

    async def fail(*args):
      if args[2] == "run_cancelled":
        raise OSError("failed cancellation")
      await original(*args)

    with patch.object(self.store, "_insert_fact", side_effect=fail):
      with self.assertRaises(OSError):
        await self.runtime.runs.cancel_run(self.thread, self.run_id)
    self.assertEqual(await self.facts(), before)
    self.assertEqual(
      (await self.runtime.runs.read_run(self.thread, self.run_id))["status"],
      "interrupted",
    )

  async def test_resume_then_cancel_publishes_once_and_waits_cleanup(self):
    entered, cleanup, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def loop(*args, execution, **kwargs):
      entered.set()
      await execution.abort_event.wait()
      cleanup.set()
      await release.wait()
      # 模拟取消请求到达时 Graph 已经自然完成，仍不得覆盖 cancelled。
      return ExecutionOutcome(ExecutionReason.COMPLETED)

    with patch("shikigen.runtime.run_execution.execute_agent_loop", side_effect=loop):
      execution = await self.runtime.runs.resume_run(
        self.thread, self.run_id, await self.responses()
      )
      await entered.wait()
      observation = await self.runtime.runs.observe_run(self.thread, self.run_id)
      result = await self.runtime.runs.cancel_run(self.thread, self.run_id)
      self.assertEqual(result["status"], "cancelled")
      await cleanup.wait()
      self.assertFalse(execution.task.done())
      new_request = asyncio.create_task(
        self.runtime.runs.start_run(self.thread, "next")
      )
      # 起跑门确认下一 Run 等待清理，而不是抢占 checkpoint。
      await asyncio.sleep(0)
      self.assertFalse(new_request.done())
      release.set()
      self.assertEqual(
        (await self.runtime.runs.wait_run(execution))["status"], "cancelled"
      )
      observed = [e.data async for e in observation if e.event == "durable_event"]
      self.assertEqual(observed, await self.facts())
      self.assertEqual(sum(e["event_type"] == "run_cancelled" for e in observed), 1)
      self.assertFalse(any(e["event_type"] == "approval_invalidated" for e in observed))
      new = await new_request
      await self.runtime.runs.cancel_run(self.thread, new.run_id)
      await self.runtime.runs.wait_run(new)

  async def test_normal_completion_wins(self):
    async def complete(*args, **kwargs):
      return ExecutionOutcome(ExecutionReason.COMPLETED)

    with patch(
      "shikigen.runtime.run_execution.execute_agent_loop", side_effect=complete
    ):
      execution = await self.runtime.runs.resume_run(
        self.thread, self.run_id, await self.responses()
      )
      completed = await self.runtime.runs.wait_run(execution)
    before = await self.facts()
    self.assertEqual(
      await self.runtime.runs.cancel_run(self.thread, self.run_id), completed
    )
    self.assertEqual(completed["status"], "completed")
    self.assertEqual(await self.facts(), before)

  async def test_disconnected_cancel_still_commits(self):
    entered, release = asyncio.Event(), asyncio.Event()
    original = self.store.cancel_run

    async def blocked(**kwargs):
      entered.set()
      await release.wait()
      return await original(**kwargs)

    with patch.object(self.store, "cancel_run", side_effect=blocked):
      caller = asyncio.create_task(
        self.runtime.runs.cancel_run(self.thread, self.run_id)
      )
      await entered.wait()
      caller.cancel()
      with self.assertRaises(asyncio.CancelledError):
        await caller
      release.set()
      # 同 Thread 后续操作排在已接受的取消之后。
      result = await self.runtime.runs.cancel_run(self.thread, self.run_id)
    self.assertEqual(result["status"], "cancelled")
    self.assertEqual(
      sum(e["event_type"] == "run_cancelled" for e in await self.facts()), 1
    )

  async def test_http_cancel_and_ownership(self):
    with patch.object(app.state, "runtime", self.runtime, create=True):
      async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
      ) as client:
        path = f"/api/threads/{self.thread}/runs/{self.run_id}/cancel"
        wrong = await client.post(f"/api/threads/wrong/runs/{self.run_id}/cancel")
        self.assertEqual(wrong.status_code, 404)
        cancelled = await client.post(path)
        self.assertEqual(cancelled.status_code, 200)
        self.assertEqual(cancelled.json()["data"]["status"], "cancelled")
        self.assertEqual((await client.post(path)).json(), cancelled.json())

  async def test_cross_connection_cancel_vs_approval(self):
    other = await ChatStore.open(self.path)
    self.addAsyncCleanup(other.close)
    responses = ApprovalSubmission(responses=await self.responses())
    results = await asyncio.gather(
      self.store.cancel_run(thread_id=self.thread, run_id=self.run_id),
      other.accept_approval_decisions(
        thread_id=self.thread, run_id=self.run_id, submission=responses
      ),
      return_exceptions=True,
    )
    self.assertFalse(isinstance(results[0], Exception))
    facts = await self.facts()
    self.assertEqual(
      (await self.store.get_run(self.run_id, self.thread))["status"], "cancelled"
    )
    if isinstance(results[1], ApprovalConflict):
      self.assertEqual(
        [e["event_type"] for e in facts[-2:]], ["approval_invalidated", "run_cancelled"]
      )
    else:
      self.assertFalse(isinstance(results[1], Exception))
      self.assertEqual(
        [e["event_type"] for e in facts[-3:]],
        ["approval_resolved", "run_running", "run_cancelled"],
      )

  async def test_completion_commit_blocks_cancel_until_publication(self):
    entered, release = asyncio.Event(), asyncio.Event()
    original = self.store.settle_execution

    async def complete(*args, **kwargs):
      return ExecutionOutcome(ExecutionReason.COMPLETED)

    async def delayed(**kwargs):
      committed = await original(**kwargs)
      entered.set()
      await release.wait()
      return committed

    with (
      patch("shikigen.runtime.run_execution.execute_agent_loop", side_effect=complete),
      patch.object(self.store, "settle_execution", side_effect=delayed),
    ):
      execution = await self.runtime.runs.resume_run(
        self.thread, self.run_id, await self.responses()
      )
      await entered.wait()
      cancel = asyncio.create_task(
        self.runtime.runs.cancel_run(self.thread, self.run_id)
      )
      await asyncio.sleep(0)
      self.assertFalse(cancel.done())
      release.set()
      self.assertEqual((await cancel)["status"], "completed")
      await self.runtime.runs.wait_run(execution)
      facts = [
        e.data async for e in execution.stream.subscribe() if e.event == "durable_event"
      ]
      self.assertEqual(facts[-1]["event_type"], "run_completed")
      self.assertFalse(any(e["event_type"] == "run_cancelled" for e in facts))
