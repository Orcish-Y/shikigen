import asyncio
import unittest

from langchain_core.messages import HumanMessage
from shikigen.contracts.runs import RunWriteResult
from shikigen.core.execution import ExecutionReason, ExecutionRegistry, RunExecution
from shikigen.core.loop import execute_agent_loop
from shikigen.runtime.run_execution import CommittedRunState, RunExecutionCoordinator
from test_loop import (
  BlockingAgent,
  FailingAgent,
  LateFailingAgent,
  MessageAgent,
)


class ControlledSettlement:
  """用同步点模拟提交接口；不声称验证了 SQLite 的事务规则。"""

  def __init__(self, *, fail=False, status="completed"):
    self.entered = asyncio.Event()
    self.allow_commit = asyncio.Event()
    self.fail = fail
    self.status = status
    self.saved = None
    self.outcome = None
    self.cancel_entered = asyncio.Event()
    self.allow_cancel = asyncio.Event()

  async def settle_execution(
    self,
    *,
    thread_id,
    run_id,
    outcome,
    error_code=None,
    invocation_seq=None,
    usage=None,
  ):
    self.outcome = outcome
    self.entered.set()
    await self.allow_commit.wait()
    if self.fail:
      raise OSError("storage unavailable")
    self.saved = CommittedRunState(self.status)
    return self.saved

  async def cancel_run(self, *, thread_id, run_id):
    self.cancel_entered.set()
    await self.allow_cancel.wait()
    return RunWriteResult(
      run={
        "id": run_id,
        "thread_id": thread_id,
        "status": "cancelled",
        "error": None,
        "error_code": None,
        "created_at": "2026-10-03T00:00:00+00:00",
        "updated_at": "2026-10-03T00:00:01+00:00",
        "completed_at": "2026-10-03T00:00:01+00:00",
        "usage": None,
        "usage_pending": True,
      },
      events=(
        {
          "id": 1,
          "thread_id": thread_id,
          "run_id": run_id,
          "seq": 1,
          "event_type": "run_cancelled",
          "category": "lifecycle",
          "event_key": f"cancelled:{run_id}",
          "content": {"status": "cancelled"},
          "metadata": {},
          "created_at": "2026-10-03T00:00:01+00:00",
        },
      ),
    )

  async def settle_execution_in_transaction(self, transaction, **kwargs):
    return await self.settle_execution(**kwargs)

  async def cancel_run_in_transaction(self, transaction, **kwargs):
    return await self.cancel_run(**kwargs)


class ExecutionTests(unittest.IsolatedAsyncioTestCase):
  async def asyncSetUp(self):
    self.registry = ExecutionRegistry()

  async def start(self, settlement, agent=None):
    self.coordinator = RunExecutionCoordinator(self.registry, settlement)
    self.addAsyncCleanup(self.coordinator.shutdown)
    return await self.coordinator.start(
      agent=agent or MessageAgent(),
      message=HumanMessage(content="hello"),
      thread_id="thread-1",
      run_id="run-1",
    )

  async def events(self, execution):
    subscription = execution.stream.subscribe()
    try:
      async with asyncio.timeout(2):
        return [event async for event in subscription]
    finally:
      await subscription.aclose()

  async def test_loop_reports_result_without_terminal_or_stream_close(self):
    for agent, reason in (
      (MessageAgent(), ExecutionReason.COMPLETED),
      (FailingAgent(), ExecutionReason.FAILED),
      (LateFailingAgent(), ExecutionReason.FAILED),
    ):
      with self.subTest(reason=reason, agent=type(agent).__name__):
        execution = RunExecution("run-1", "thread-1")
        result = await execute_agent_loop(
          agent, HumanMessage(content="hello"), execution=execution
        )
        self.assertEqual(result.reason, reason)
        # Loop 已返回，应用仍能提交后发布。
        execution.stream.publish("metadata", {"run_id": "still-open"})
        execution.stream.close()
        events = await self.events(execution)
        self.assertFalse(any(event.event in ("status", "error") for event in events))
        if reason is ExecutionReason.FAILED:
          self.assertIsInstance(result.error, Exception)

  async def test_cooperative_abort_is_only_an_execution_result(self):
    execution = RunExecution("run-1", "thread-1")
    execution.request_cancel()
    async with asyncio.timeout(2):
      result = await execute_agent_loop(
        BlockingAgent(), HumanMessage(content="hello"), execution=execution
      )
    self.assertEqual(result.reason, ExecutionReason.ABORTED)
    execution.stream.close()
    self.assertFalse(any(e.event == "status" for e in await self.events(execution)))

  async def test_disconnect_does_not_own_execution_or_other_subscription(self):
    settlement = ControlledSettlement()
    execution = await self.start(settlement)
    first = execution.stream.subscribe()
    second = execution.stream.subscribe()
    self.addAsyncCleanup(first.aclose)
    self.addAsyncCleanup(second.aclose)
    await asyncio.wait_for(settlement.entered.wait(), 2)
    await first.aclose()
    self.assertFalse(execution.task.done())
    self.assertIs(self.registry.get("thread-1", "run-1"), execution)
    # 阻塞提交时，以显式标记确认之前没有终态，也没有提前关流。
    execution.stream.publish("metadata", {"run_id": "before-commit"})
    prefix = []
    async with asyncio.timeout(2):
      async for event in second:
        prefix.append(event)
        if event.data == {"run_id": "before-commit"}:
          break
    self.assertFalse(any(e.event == "status" for e in prefix))
    settlement.allow_commit.set()
    await asyncio.wait_for(execution.task, 2)
    remaining = [event async for event in second]
    self.assertEqual(remaining[-1].data, {"status": "completed"})
    self.assertIsNone(self.registry.get("thread-1", "run-1"))
    self.assertEqual(settlement.saved.status, "completed")

  async def test_persistence_failure_never_publishes_success(self):
    settlement = ControlledSettlement(fail=True)
    execution = await self.start(settlement)
    settlement.allow_commit.set()
    with self.assertLogs("shikigen.runtime.run_execution", level="ERROR"):
      with self.assertRaisesRegex(OSError, "storage unavailable"):
        await asyncio.wait_for(execution.task, 2)
    events = await self.events(execution)
    self.assertFalse(any(e.event in ("status", "error") for e in events))
    self.assertEqual(events[-1].event, "stream_failed")
    self.assertIsNone(self.registry.get("thread-1", "run-1"))

  async def test_committed_cancellation_wins_over_loop_completion(self):
    settlement = ControlledSettlement(status="cancelled")
    execution = await self.start(settlement)
    settlement.allow_commit.set()
    await asyncio.wait_for(execution.task, 2)
    self.assertEqual(settlement.outcome.reason, ExecutionReason.COMPLETED)
    events = await self.events(execution)
    self.assertEqual(events[-1].data, {"status": "cancelled"})
    self.assertFalse(any(e.data == {"status": "completed"} for e in events))

  async def test_shutdown_waits_for_graph_cleanup_without_committing_cancel(self):
    entered = asyncio.Event()
    cleaned = asyncio.Event()

    class Agent(BlockingAgent):
      async def astream_events(self, *args, **kwargs):
        stream = await super().astream_events(*args, **kwargs)

        class Context:
          async def __aenter__(self):
            entered.set()
            return stream

          async def __aexit__(self, *args):
            await asyncio.sleep(0)
            cleaned.set()

        return Context()

    settlement = ControlledSettlement()
    execution = await self.start(settlement, Agent())
    await asyncio.wait_for(entered.wait(), 2)
    await asyncio.wait_for(self.coordinator.shutdown(), 2)
    self.assertTrue(execution.task.cancelled())
    self.assertTrue(cleaned.is_set())
    self.assertFalse(settlement.entered.is_set())
    self.assertIsNone(self.registry.get("thread-1", "run-1"))
    events = await self.events(execution)
    self.assertEqual(events[-1].event, "stream_failed")
    self.assertFalse(any(e.event == "status" for e in events))

  async def test_shutdown_before_task_starts_closes_subscription(self):
    execution = await self.start(ControlledSettlement())
    await self.coordinator.shutdown()
    self.assertTrue(execution.task.cancelled())
    self.assertEqual(await self.events(execution), [])
    self.assertIsNone(self.registry.get("thread-1", "run-1"))

  async def test_prestart_task_cancel_waits_for_accepted_cancellation_publication(self):
    settlement = ControlledSettlement()
    execution = await self.start(settlement)
    subscription = execution.stream.subscribe()
    self.addAsyncCleanup(subscription.aclose)
    execution.task.cancel()
    cancellation = asyncio.create_task(self.coordinator.cancel("thread-1", "run-1"))
    try:
      await asyncio.wait_for(settlement.cancel_entered.wait(), 2)
      # done callback 的清理必须等待取消事务，不能提前关流或移除句柄。
      execution.stream.publish("metadata", {"run_id": "before-cancel-commit"})
      self.assertIs(self.registry.get("thread-1", "run-1"), execution)
    finally:
      settlement.allow_cancel.set()
    self.assertEqual((await cancellation)["status"], "cancelled")
    async with asyncio.timeout(2):
      events = [event async for event in subscription]
    self.assertEqual(events[-1].data, {"status": "cancelled"})
    self.assertEqual(
      [e.data["event_type"] for e in events if e.event == "durable_event"],
      ["run_cancelled"],
    )
    self.assertIsNone(self.registry.get("thread-1", "run-1"))

  async def test_duplicate_install_and_old_cleanup_do_not_replace_new_execution(self):
    first = RunExecution("run-1", "thread-1")
    second = RunExecution("run-1", "thread-1")
    self.registry.install(first)
    with self.assertRaises(RuntimeError):
      self.registry.install(second)
    self.assertIsNone(self.registry.get("wrong-thread", "run-1"))
    self.registry.remove(first)
    self.registry.install(second)
    self.registry.remove(first)
    self.assertIs(self.registry.get("thread-1", "run-1"), second)
