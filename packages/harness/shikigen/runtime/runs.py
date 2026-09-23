"""产品 Run 的创建、执行协调、等待与查询。"""

import asyncio
import uuid
from collections.abc import Callable, Coroutine
from contextlib import nullcontext
from functools import partial
from typing import Any
from weakref import WeakValueDictionary

from langchain_core.messages import HumanMessage
from langgraph.types import Command

from shikigen.contracts.events import (
  ApprovalInvalidated,
  ApprovalRequired,
  ApprovalResolved,
  ApprovalSubmission,
  InterruptResponse,
  Usage,
)
from shikigen.contracts.messages import message_identity
from shikigen.contracts.runs import (
  AcceptedApproval,
  ApprovalConflict,
  CommittedEvent,
  CommittedRunState,
  ExecutionStopped,
  InvalidRunState,
  MessageConflict,
  ObservationUnavailable,
  RunNotFound,
  RunSnapshot,
  RunStatus,
  RunWriteResult,
  ThreadBusy,
  ThreadNotFound,
)
from shikigen.contracts.stream import UsageData
from shikigen.core.approval import validate_responses
from shikigen.core.execution import (
  ExecutionOutcome,
  ExecutionReason,
  ExecutionRegistry,
  RunExecution,
)
from shikigen.core.graph_pause import GraphPauseCollector
from shikigen.persistence import ChatStore
from shikigen.runtime.lifecycle import ApplicationLifecycle
from shikigen.runtime.run_events import RunEventIngestor
from shikigen.runtime.run_execution import start_run_execution
from shikigen.runtime.run_observation import RunObservation
from shikigen.utils.text_safety import replace_surrogates


class RunTransitions:
  """持久 Run 的状态变更；检查、状态与事件在同一事务内完成。

  不启动 Graph 或停止本地任务。返回已提交结果，由 RunService 和执行
  编排负责后续动作；事件写入统一经过 RunEventIngestor。
  """

  def __init__(self, store: ChatStore) -> None:
    self._store = store

  async def create_run(
    self,
    *,
    run_id: str,
    thread_id: str,
    entry_message: HumanMessage,
  ) -> RunWriteResult:
    """在一个写事务中检查排他并提交 Run、running 事实和入口消息。

    BEGIN IMMEDIATE 使本接口在多个连接间也串行检查。
    新库有 schema 排他约束；数据库必须使用当前 schema。
    """
    message_identity(
      {
        "type": "human",
        "content": entry_message.content,
        "message_id": entry_message.id,
      }
    )
    async with self._store.transaction() as tx:
      if not await tx.runs.thread_exists(thread_id):
        raise ThreadNotFound("Thread not found")
      if await tx.runs.has_active_run(thread_id):
        raise ThreadBusy("Thread is busy with another run")
      if await tx.events.message_by_key(thread_id, f"human:{entry_message.id}"):
        raise MessageConflict("Entry message already belongs to a run")
      await tx.runs.insert_run(run_id, thread_id, RunStatus.RUNNING)
      await RunEventIngestor.write_in_transaction(
        tx,
        thread_id,
        run_id,
        "run_running",
        "lifecycle",
        f"running:{run_id}",
        {"status": "running"},
      )
      await RunEventIngestor.write_in_transaction(
        tx,
        thread_id,
        run_id,
        "human_message",
        "message",
        f"human:{entry_message.id}",
        {
          "type": "human",
          "content": entry_message.content,
          "message_id": entry_message.id,
        },
      )
      await tx.runs.touch_thread(thread_id)
      run = await tx.runs.read_run(run_id, thread_id)
      assert run is not None
      events = await tx.events.read_events(thread_id, run_id)
      return RunWriteResult(run, tuple(events))

  async def settle_execution(
    self,
    *,
    thread_id: str,
    run_id: str,
    outcome: ExecutionOutcome,
    error_code: str | None = None,
    invocation_seq: int | None = None,
    usage: UsageData | None = None,
  ) -> CommittedRunState:
    """只有 running 能结算；已有终态或暂停事实原样返回，禁止覆盖。"""
    target = {
      ExecutionReason.COMPLETED: RunStatus.COMPLETED,
      ExecutionReason.ABORTED: RunStatus.CANCELLED,
      ExecutionReason.FAILED: RunStatus.ERROR,
      ExecutionReason.INTERRUPTED: RunStatus.INTERRUPTED,
    }[outcome.reason]
    if error_code is not None and (
      outcome.reason is not ExecutionReason.FAILED or not error_code.strip()
    ):
      raise ValueError("Only failed execution accepts a nonempty error code")
    if outcome.reason is ExecutionReason.FAILED:
      error_code = error_code or "execution_failed"
    error = str(outcome.error) if outcome.error is not None else None
    approval = None
    if outcome.pause is not None:
      approval = ApprovalRequired.model_validate(
        {
          "checkpoint": outcome.pause.checkpoint,
          "interrupts": list(outcome.pause.interrupts),
        }
      )
      if approval.checkpoint.configurable.thread_id != thread_id:
        raise ValueError("Approval checkpoint belongs to another Thread")
    async with self._store.transaction() as tx:
      row = await tx.runs.read_run(run_id, thread_id)
      if row is None:
        raise RunNotFound("Run not found")
      history = await tx.events.read_events(thread_id, run_id)
      running = next(e for e in reversed(history) if e["event_type"] == "run_running")
      if invocation_seq is not None and invocation_seq != running["seq"]:
        raise InvalidRunState("A stale invocation cannot settle the current execution")
      if usage is not None:
        validated = Usage.model_validate(usage).model_dump(mode="json")
        previous = await tx.runs.read_invocation_usage(
          thread_id, run_id, running["seq"]
        )
        if previous is not None and previous != validated:
          raise InvalidRunState("Invocation usage conflicts with its settled usage")
        if previous is None:
          await tx.runs.insert_usage(thread_id, run_id, running["seq"], validated)
      total_usage, _ = await tx.runs.read_usage(run_id, thread_id)
      settlement_key = f"settled:{run_id}:{running['seq']}"
      if row["status"] != RunStatus.RUNNING:
        event = None
        if row["status"] == RunStatus.CANCELLED:
          event = await tx.events.event_by_key(thread_id, run_id, f"cancelled:{run_id}")
        if event is None:
          event = await tx.events.event_by_key(thread_id, run_id, settlement_key)
        if event is None or event["content"].get("status") != row["status"]:
          raise InvalidRunState("Run is missing its matching settlement fact")
        events = [event]
        if row["status"] == RunStatus.CANCELLED:
          events = [
            e for e in history if e["event_type"] == "approval_invalidated"
          ] + events
        if row["status"] == RunStatus.INTERRUPTED:
          events = [
            e
            for e in history
            if e["event_type"] == "approval_required" and e["seq"] > running["seq"]
          ] + events
          if len(events) != 2:
            raise InvalidRunState("Paused Run is missing its approval fact")
        committed = CommittedRunState(
          RunStatus(row["status"]),
          row["error"],
          row["error_code"],
          tuple(events),
          changed=False,
          usage=total_usage,
        )
        return committed
      changed = await tx.runs.update_state(
        run_id,
        thread_id,
        status=target,
        error=error,
        error_code=error_code,
        terminal=target.terminal,
        expected_status=RunStatus.RUNNING,
      )
      if not changed:
        raise InvalidRunState("Run state changed during settlement")
      content: dict[str, Any] = {"status": target}
      if error is not None:
        content["message"] = error
        content["error_code"] = error_code
      events = []
      if approval is not None:
        key = f"approval:required:{approval.checkpoint.configurable.checkpoint_id}"
        await RunEventIngestor.write_in_transaction(
          tx,
          thread_id,
          run_id,
          "approval_required",
          "approval",
          key,
          approval.model_dump(mode="json"),
        )
        required = await tx.events.event_by_key(thread_id, run_id, key)
        assert required is not None
        events.append(required)
      await RunEventIngestor.write_in_transaction(
        tx,
        thread_id,
        run_id,
        f"run_{target}",
        "lifecycle",
        settlement_key,
        content,
      )
      await tx.runs.touch_thread(thread_id)
      event = await tx.events.event_by_key(thread_id, run_id, settlement_key)
      assert event is not None
      return CommittedRunState(
        target, error, error_code, (*events, event), usage=total_usage
      )

  async def cancel_run(
    self,
    *,
    thread_id: str,
    run_id: str,
  ) -> RunWriteResult:
    """原子取消运行或暂停；终态幂等返回，不覆盖第一次有效提交。"""
    async with self._store.transaction() as tx:
      run = await tx.runs.read_run(run_id, thread_id)
      if run is None:
        raise RunNotFound("Run not found")
      if RunStatus(run["status"]).terminal:
        return RunWriteResult(run, ())
      history = await tx.events.read_events(thread_id, run_id)
      keys = []
      if run["status"] == "interrupted":
        pending = next(
          (e for e in reversed(history) if e["category"] == "approval"), None
        )
        if pending is None or pending["event_type"] != "approval_required":
          raise InvalidRunState("Paused Run is missing its pending approval")
        required = ApprovalRequired.model_validate(pending["content"])
        invalidated = ApprovalInvalidated(
          checkpoint=required.checkpoint,
          interrupt_ids=[item.id for item in required.interrupts],
        )
        key = f"approval:invalidated:{required.checkpoint.configurable.checkpoint_id}"
        await RunEventIngestor.write_in_transaction(
          tx,
          thread_id,
          run_id,
          "approval_invalidated",
          "approval",
          key,
          invalidated.model_dump(mode="json"),
        )
        keys.append(key)
      key = f"cancelled:{run_id}"
      await RunEventIngestor.write_in_transaction(
        tx,
        thread_id,
        run_id,
        "run_cancelled",
        "lifecycle",
        key,
        {"status": "cancelled"},
      )
      keys.append(key)
      await tx.runs.update_state(
        run_id,
        thread_id,
        status=RunStatus.CANCELLED,
        terminal=True,
      )
      await tx.runs.touch_thread(thread_id)
      updated = await tx.runs.read_run(run_id, thread_id)
      assert updated is not None
      events = []
      for key in keys:
        event = await tx.events.event_by_key(thread_id, run_id, key)
        assert event is not None
        events.append(event)
      return RunWriteResult(updated, tuple(events))

  async def accept_approval_decisions(
    self,
    *,
    thread_id: str,
    run_id: str,
    submission: ApprovalSubmission,
  ) -> AcceptedApproval:
    """串行检查当前暂停，原子保存响应与 running；不调用 Graph。"""
    async with self._store.transaction() as tx:
      run = await tx.runs.read_run(run_id, thread_id)
      if run is None:
        raise RunNotFound("Run not found")
      if run["status"] != RunStatus.INTERRUPTED:
        raise ApprovalConflict("Run is not waiting for approval; read current facts")
      history = await tx.events.read_events(thread_id, run_id)
      last_approval = next(
        (e for e in reversed(history) if e["category"] == "approval"), None
      )
      if last_approval is None or last_approval["event_type"] != "approval_required":
        raise InvalidRunState("Paused Run is missing its pending approval")
      required = ApprovalRequired.model_validate(last_approval["content"])
      if required.checkpoint.configurable.thread_id != thread_id:
        raise InvalidRunState("Approval belongs to another Thread")
      resume = validate_responses(required, submission)
      resolved = ApprovalResolved(
        checkpoint=required.checkpoint, responses=submission.responses
      )
      checkpoint_id = required.checkpoint.configurable.checkpoint_id
      resolved_key = f"approval:resolved:{checkpoint_id}"
      running_key = f"running:{run_id}:{checkpoint_id}"
      await RunEventIngestor.write_in_transaction(
        tx,
        thread_id,
        run_id,
        "approval_resolved",
        "approval",
        resolved_key,
        resolved.model_dump(mode="json", exclude_none=True),
      )
      await RunEventIngestor.write_in_transaction(
        tx,
        thread_id,
        run_id,
        "run_running",
        "lifecycle",
        running_key,
        {"status": "running"},
      )
      await tx.runs.update_state(
        run_id,
        thread_id,
        status=RunStatus.RUNNING,
        terminal=False,
      )
      await tx.runs.touch_thread(thread_id)
      resolved_event = await tx.events.event_by_key(thread_id, run_id, resolved_key)
      running_event = await tx.events.event_by_key(thread_id, run_id, running_key)
      assert resolved_event is not None and running_event is not None
      return AcceptedApproval(
        required.checkpoint.model_dump(mode="json"),
        resume,
        (resolved_event, running_event),
      )


class RunService:
  def __init__(
    self,
    *,
    agent: Any,
    store: ChatStore,
    executions: ExecutionRegistry,
    lifecycle: ApplicationLifecycle,
    ingestor: RunEventIngestor | None = None,
  ) -> None:
    self._thread_locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()
    self.agent = agent
    self._store = store
    self._executions = executions
    self._lifecycle = lifecycle
    self._transitions = RunTransitions(store)
    self._ingestor = (
      ingestor if ingestor is not None else RunEventIngestor(store, executions)
    )

  async def _accept[T](
    self, thread_id: str, operation: Callable[[], Coroutine[Any, Any, T]]
  ) -> T:
    async def coordinated() -> T:
      lock = self._thread_locks.setdefault(thread_id, asyncio.Lock())
      async with lock:
        return await operation()

    return await self._lifecycle.accept(coordinated())

  async def start_run(self, thread_id: str, message: str) -> RunExecution:
    async def start() -> RunExecution:
      # 持久取消先释放产品槽位，但旧 Graph 必须退出后才能使用同一 checkpoint。
      for previous in self._executions.for_thread(thread_id):
        run = await self.read_run(thread_id, previous.run_id)
        if RunStatus(run["status"]).terminal and previous.task is not None:
          await asyncio.shield(asyncio.gather(previous.task, return_exceptions=True))
      run_id = uuid.uuid4().hex
      entry = HumanMessage(id=uuid.uuid4().hex, content=replace_surrogates(message))
      created = await self._transitions.create_run(
        run_id=run_id,
        thread_id=thread_id,
        entry_message=entry,
      )
      try:
        return start_run_execution(
          agent=self.agent,
          message=entry,
          thread_id=thread_id,
          run_id=run_id,
          registry=self._executions,
          settlement=self._transitions,
          initial_events=created.events,
          ingest_message=partial(
            self._ingestor.ingest_message, thread_id=thread_id, run_id=run_id
          ),
          ingest_delta=partial(
            self._ingestor.ingest_delta,
            thread_id=thread_id,
            run_id=run_id,
          ),
        )
      except Exception as error:
        await self._transitions.settle_execution(
          thread_id=thread_id,
          run_id=run_id,
          outcome=ExecutionOutcome(ExecutionReason.FAILED, error=error),
        )
        raise

    return await self._accept(thread_id, start)

  async def resume_run(
    self,
    thread_id: str,
    run_id: str,
    responses: dict[str, InterruptResponse] | dict[str, Any],
  ) -> RunExecution:
    """接受当前全部审批响应；同 Run 在准确 checkpoint 上开启下一次执行。

    冲突后读取既有事实收敛。调用者断开不撤销已接收的响应或后台执行。
    """
    submission = ApprovalSubmission.model_validate({"responses": responses})

    async def resume() -> RunExecution:
      run = await self.read_run(thread_id, run_id)
      if run["status"] != "interrupted":
        raise ApprovalConflict("Run is not waiting for approval; read current facts")
      previous = self._executions.get(thread_id, run_id)
      if previous is not None:
        await self.wait_run(previous)
      history = await self._store.list_run_events(thread_id, run_id)
      # 这里存疑：是否需要判断最新的数据是不是当前待判断的 interrupt？
      # 找最后一个 approval 好像没什么用吧。
      pending = next(
        (e for e in reversed(history) if e["category"] == "approval"), None
      )
      if pending is None or pending["event_type"] != "approval_required":
        raise ApprovalConflict("Pending approval changed; read current facts")
      required = ApprovalRequired.model_validate(pending["content"])
      validate_responses(required, submission)
      collector = GraphPauseCollector(thread_id)
      collector.checkpoint = required.checkpoint.model_dump(mode="json")
      try:
        pause = await collector.read_pause(self.agent)
      except Exception as error:
        raise InvalidRunState(
          "Approval checkpoint cannot be verified; retry later"
        ) from error
      expected = {item.id: item.model_dump(mode="json") for item in required.interrupts}
      if pause is None or {item["id"]: item for item in pause.interrupts} != expected:
        raise InvalidRunState("Checkpoint Interrupts do not match pending approval")
      accepted = await self._transitions.accept_approval_decisions(
        thread_id=thread_id, run_id=run_id, submission=submission
      )
      try:
        return start_run_execution(
          agent=self.agent,
          message=Command(resume=accepted.resume),
          checkpoint=accepted.checkpoint,
          thread_id=thread_id,
          run_id=run_id,
          registry=self._executions,
          settlement=self._transitions,
          initial_events=accepted.events,
          ingest_message=partial(
            self._ingestor.ingest_message, thread_id=thread_id, run_id=run_id
          ),
          ingest_delta=partial(
            self._ingestor.ingest_delta, thread_id=thread_id, run_id=run_id
          ),
        )
      except Exception as error:
        await self._transitions.settle_execution(
          thread_id=thread_id,
          run_id=run_id,
          outcome=ExecutionOutcome(ExecutionReason.FAILED, error=error),
          error_code="resume_start_failed",
          invocation_seq=accepted.events[-1]["seq"],
        )
        raise

    return await self._accept(thread_id, resume)

  async def cancel_run(self, thread_id: str, run_id: str) -> RunSnapshot:
    """先提交取消，再通知本地协作停止；终态返回已有结果。"""

    async def cancel() -> RunSnapshot:
      execution = self._executions.get(thread_id, run_id)
      async with execution.settlement_lock if execution is not None else nullcontext():
        result = await self._transitions.cancel_run(thread_id=thread_id, run_id=run_id)
        if execution is not None and result.run["status"] == "cancelled":
          if result.events:
            RunEventIngestor.publish(
              execution.stream,
              result.events,
              settlement=CommittedRunState(RunStatus.CANCELLED, events=result.events),
            )
          execution.request_cancel()
        return result.run

    return await self._accept(thread_id, cancel)

  async def wait_run(self, execution: RunExecution) -> RunSnapshot:
    """等待这次执行及持久化收尾，返回已提交状态（包括 interrupted）。

    句柄在注册表移除后仍可等待。停止等待不取消执行；Task 异常原样传播。
    跨进程或只保存了 ID 的调用方使用 read_run，不从 EOF 推断完成。
    """
    task = execution.task
    if task is None:
      raise ValueError("Execution has not been started")
    try:
      await asyncio.shield(task)
    except asyncio.CancelledError:
      if task.cancelled():
        raise ExecutionStopped(
          "Local execution stopped without a committed result"
        ) from None
      raise
    row = await self.read_run(execution.thread_id, execution.run_id)
    status = RunStatus(row["status"])
    if not status.terminal and status is not RunStatus.INTERRUPTED:
      raise ExecutionStopped("Execution ended without a committed result")
    return row

  async def read_run(self, thread_id: str, run_id: str) -> RunSnapshot:
    row = await self._store.get_run(run_id, thread_id)
    if row is None:
      raise RunNotFound("Run not found")
    return row

  async def list_run_messages(
    self, thread_id: str, run_id: str
  ) -> list[CommittedEvent]:
    messages = await self._store.list_messages_by_run(thread_id, run_id)
    if messages is None:
      raise RunNotFound("Run not found")
    return messages

  async def list_run_events(self, thread_id: str, run_id: str) -> list[CommittedEvent]:
    return await self._store.list_run_events(thread_id, run_id)

  async def observe_run(self, thread_id: str, run_id: str) -> RunObservation:
    """全量重建并跟随已有执行；返回后调用者负责 aclose。

    数据库只交付 invocation 起点之前的事实，不能把查询时 MAX(seq)
    当作提交水位；本次 invocation 由完整缓存和实时订阅交付。

    Raises:
      RunNotFound: 指定 Thread 或 Run 不存在。
      ObservationUnavailable: Run 仍在运行但本地无活跃执行对象，可稍后重试。
    """
    run = await self.read_run(thread_id, run_id)
    execution = None
    # todo. 这里后面看看能不能优化一下
    if run["status"] == "running":
      execution = self._executions.get(thread_id, run_id)
      if execution is None:
        # 首次读取之后执行可能已经完成并从注册表移除。
        run = await self.read_run(thread_id, run_id)
        if run["status"] == "running":
          raise ObservationUnavailable("Local execution unavailable; retry observation")
    subscription = execution.stream.subscribe() if execution is not None else None
    try:
      history = await self._store.list_run_events(thread_id, run_id)
      if execution is not None:
        history = [e for e in history if e["seq"] < execution.replay_start_seq]
      return RunObservation(run, history, subscription)
    except BaseException:
      if subscription is not None:
        await subscription.aclose()
      raise
