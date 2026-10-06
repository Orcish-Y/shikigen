"""产品 Run 的创建、执行协调、等待与查询。"""

import asyncio
import uuid
from collections.abc import Callable, Coroutine
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
from shikigen.persistence import ChatStore
from shikigen.persistence.chat_store import RunTransaction
from shikigen.persistence.database import committed_query
from shikigen.runtime.lifecycle import ApplicationLifecycle
from shikigen.runtime.recovery import RunRecoveryCoordinator
from shikigen.runtime.run_events import RunEventIngestor
from shikigen.runtime.run_execution import RunExecutionCoordinator
from shikigen.runtime.run_observation import RunObservation
from shikigen.utils.text_safety import replace_surrogates


class RunTransitions:
  """持久 Run 的状态变更；检查、状态与事件在同一事务内完成。

  不启动 Graph 或停止本地任务。独立入口返回已提交结果；事务内入口由
  调用方提交后发布。消息使用 EventStore 的统一写入入口。
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
      await tx.events.write_message_in_transaction(
        thread_id=thread_id,
        run_id=run_id,
        message={
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
    """独立结算入口；事务成功退出后返回已提交的状态与事实。"""
    async with self._store.transaction() as transaction:
      return await self.settle_execution_in_transaction(
        transaction,
        thread_id=thread_id,
        run_id=run_id,
        outcome=outcome,
        error_code=error_code,
        invocation_seq=invocation_seq,
        usage=usage,
      )

  async def settle_execution_in_transaction(
    self,
    transaction: RunTransaction,
    *,
    thread_id: str,
    run_id: str,
    outcome: ExecutionOutcome,
    error_code: str | None = None,
    invocation_seq: int | None = None,
    usage: UsageData | None = None,
  ) -> CommittedRunState:
    """事务内结算状态；不提交、不接入消息，调用方提交后才能发布结果。"""
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
    row = await transaction.runs.read_run(run_id, thread_id)
    if row is None:
      raise RunNotFound("Run not found")
    history = await transaction.events.read_events(thread_id, run_id)
    running_event = next(
      e for e in reversed(history) if e["event_type"] == "run_running"
    )
    if invocation_seq is not None and invocation_seq != running_event["seq"]:
      raise InvalidRunState("A stale invocation cannot settle the current execution")
    if usage is not None:
      validated = Usage.model_validate(usage).model_dump(mode="json")
      previous = await transaction.runs.read_invocation_usage(
        thread_id, run_id, running_event["seq"]
      )
      if previous is not None and previous != validated:
        raise InvalidRunState("Invocation usage conflicts with its settled usage")
      if previous is None:
        await transaction.runs.insert_usage(
          thread_id, run_id, running_event["seq"], validated
        )
    total_usage, _ = await transaction.runs.read_usage(run_id, thread_id)
    settlement_key = f"settled:{run_id}:{running_event['seq']}"
    if row["status"] != RunStatus.RUNNING:
      event = None
      if row["status"] == RunStatus.CANCELLED:
        event = await transaction.events.event_by_key(
          thread_id, run_id, f"cancelled:{run_id}"
        )
      if event is None:
        event = await transaction.events.event_by_key(thread_id, run_id, settlement_key)
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
          if e["event_type"] == "approval_required" and e["seq"] > running_event["seq"]
        ] + events
        if len(events) != 2:
          raise InvalidRunState("Paused Run is missing its approval fact")
      settlement = CommittedRunState(
        RunStatus(row["status"]),
        row["error"],
        row["error_code"],
        tuple(events),
        changed=False,
        usage=total_usage,
      )
      return settlement
    events = []
    changed = await transaction.runs.update_state(
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
    if target is RunStatus.ERROR:
      content["message"] = error
      content["error_code"] = error_code
    if approval is not None:
      key = f"approval:required:{approval.checkpoint.configurable.checkpoint_id}"
      await RunEventIngestor.write_in_transaction(
        transaction,
        thread_id,
        run_id,
        "approval_required",
        "approval",
        key,
        approval.model_dump(mode="json"),
      )
      required = await transaction.events.event_by_key(thread_id, run_id, key)
      assert required is not None
      events.append(required)
    await RunEventIngestor.write_in_transaction(
      transaction,
      thread_id,
      run_id,
      f"run_{target}",
      "lifecycle",
      settlement_key,
      content,
    )
    await transaction.runs.touch_thread(thread_id)
    event = await transaction.events.event_by_key(thread_id, run_id, settlement_key)
    assert event is not None
    return CommittedRunState(
      target, error, error_code, (*events, event), usage=total_usage
    )

  async def fail_recovery(
    self, expected: RunSnapshot, error_code: str, message: str
  ) -> RunSnapshot:
    """恢复失败与错误事实共同提交；检查扫描后的状态没有被其他操作改变。"""
    thread_id, run_id = expected["thread_id"], expected["id"]
    async with self._store.transaction() as tx:
      run = await tx.runs.read_run(run_id, thread_id)
      if run is None:
        raise RunNotFound("Run not found")
      if run != expected or RunStatus(run["status"]).terminal:
        return run
      await RunEventIngestor.write_in_transaction(
        tx,
        thread_id,
        run_id,
        "run_error",
        "lifecycle",
        f"recovery:{run_id}:{error_code}",
        {"status": "error", "message": message, "error_code": error_code},
      )
      await tx.runs.update_state(
        run_id,
        thread_id,
        status=RunStatus.ERROR,
        terminal=True,
        error=message,
        error_code=error_code,
        expected_status=run["status"],
      )
      await tx.runs.touch_thread(thread_id)
      updated = await tx.runs.read_run(run_id, thread_id)
      assert updated is not None
      return updated

  async def cancel_run(self, *, thread_id: str, run_id: str) -> RunWriteResult:
    """独立取消入口；事务成功退出后返回实际已提交的状态与事实。"""
    async with self._store.transaction() as transaction:
      return await self.cancel_run_in_transaction(
        transaction, thread_id=thread_id, run_id=run_id
      )

  async def cancel_run_in_transaction(
    self,
    transaction: RunTransaction,
    *,
    thread_id: str,
    run_id: str,
  ) -> RunWriteResult:
    """事务内取消运行或暂停；不提交、不接入消息，已有终态原样返回。"""
    run = await transaction.runs.read_run(run_id, thread_id)
    if run is None:
      raise RunNotFound("Run not found")
    if RunStatus(run["status"]).terminal:
      return RunWriteResult(run, ())
    history = await transaction.events.read_events(thread_id, run_id)
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
        transaction,
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
      transaction,
      thread_id,
      run_id,
      "run_cancelled",
      "lifecycle",
      key,
      {"status": "cancelled"},
    )
    keys.append(key)
    await transaction.runs.update_state(
      run_id,
      thread_id,
      status=RunStatus.CANCELLED,
      terminal=True,
    )
    await transaction.runs.touch_thread(thread_id)
    updated = await transaction.runs.read_run(run_id, thread_id)
    assert updated is not None
    events = []
    for key in keys:
      event = await transaction.events.event_by_key(thread_id, run_id, key)
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
    transitions: RunTransitions,
    coordinator: RunExecutionCoordinator,
  ) -> None:
    self._thread_locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()
    self.agent = agent
    self._store = store
    self._executions = executions
    self._lifecycle = lifecycle
    self._transitions = transitions
    self._coordinator = coordinator
    self.recovery = RunRecoveryCoordinator(
      agent=agent, store=store, executions=executions, transitions=self._transitions
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
        run = await self._read_run(thread_id, previous.run_id)
        if RunStatus(run["status"]).terminal:
          await self._coordinator.drain(previous)
      run_id = uuid.uuid4().hex
      entry = HumanMessage(id=uuid.uuid4().hex, content=replace_surrogates(message))
      created = await self._transitions.create_run(
        run_id=run_id,
        thread_id=thread_id,
        entry_message=entry,
      )
      return await self._coordinator.start(
        agent=self.agent,
        message=entry,
        thread_id=thread_id,
        run_id=run_id,
        initial_events=created.events,
      )

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
      run = await self._read_run(thread_id, run_id)
      if run["status"] != "interrupted":
        raise ApprovalConflict("Run is not waiting for approval; read current facts")
      previous = self._executions.get(thread_id, run_id)
      if previous is not None:
        await self.wait_run(previous)
      checked = await self.recovery.reconcile_run(thread_id, run_id)
      if checked["status"] != "interrupted":
        raise InvalidRunState("Approval state is corrupt; read current facts")
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
      accepted = await self._transitions.accept_approval_decisions(
        thread_id=thread_id, run_id=run_id, submission=submission
      )
      return await self._coordinator.start(
        agent=self.agent,
        message=Command(resume=accepted.resume),
        checkpoint=accepted.checkpoint,
        thread_id=thread_id,
        run_id=run_id,
        initial_events=accepted.events,
      )

    return await self._accept(thread_id, resume)

  async def cancel_run(self, thread_id: str, run_id: str) -> RunSnapshot:
    """先提交取消，再通知本地协作停止；终态返回已有结果。"""

    return await self._accept(
      thread_id, lambda: self._coordinator.cancel(thread_id, run_id)
    )

  async def wait_run(self, execution: RunExecution) -> RunSnapshot:
    """等待这次执行及持久化收尾，返回已提交状态（包括 interrupted）。

    句柄在注册表移除后仍可等待。停止等待不取消执行；Task 异常原样传播。
    跨进程或只保存了 ID 的调用方使用 read_run，不从 EOF 推断完成。
    """
    await self._coordinator.wait(execution)
    row = await self._read_run(execution.thread_id, execution.run_id)
    status = RunStatus(row["status"])
    if not status.terminal and status is not RunStatus.INTERRUPTED:
      raise ExecutionStopped("Execution ended without a committed result")
    return row

  async def read_run(self, thread_id: str, run_id: str) -> RunSnapshot:
    async def read() -> RunSnapshot:
      run = await self._read_run(thread_id, run_id)
      if run["status"] == "interrupted":
        return await self.recovery.reconcile_run(thread_id, run_id)
      return run

    lock = self._thread_locks.setdefault(thread_id, asyncio.Lock())
    async with lock:
      return await read()

  async def get_run_snapshot(self, thread_id: str, run_id: str) -> RunSnapshot:
    """只读已提交快照；不校验 checkpoint、不恢复执行、不写恢复错误。"""
    with committed_query():
      run = await self._read_run(thread_id, run_id)
      RunStatus(run["status"])
      return run

  async def _read_run(self, thread_id: str, run_id: str) -> RunSnapshot:
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
    """纯读有序已提交事件；不执行 checkpoint 恢复或写入运行状态。"""
    with committed_query():
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
    if run["status"] == "running":
      execution = self._executions.get(thread_id, run_id)
      if execution is None:
        # 首次读取之后执行可能已经完成并从注册表移除。
        run = await self.read_run(thread_id, run_id)
        if run["status"] == "running":
          raise ObservationUnavailable("Local execution unavailable; retry observation")
    return await RunObservation.rebuild(run, store=self._store, execution=execution)
