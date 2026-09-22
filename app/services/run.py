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
from shikigen.event_contract import (
  ApprovalRequired,
  ApprovalSubmission,
  InterruptResponse,
)
from shikigen.execution import (
  ExecutionOutcome,
  ExecutionReason,
  ExecutionRegistry,
  RunExecution,
)
from shikigen.graph_pause import GraphPauseCollector
from shikigen.utils.text_safety import replace_surrogates

from app.approval import validate_responses
from app.lifecycle import ApplicationLifecycle
from app.persistence import ChatStore
from app.run_events import RunEventIngestor
from app.run_execution import start_run_execution
from app.run_observation import RunObservation
from app.run_state import (
  ApprovalConflict,
  CommittedEvent,
  CommittedRunState,
  ExecutionStopped,
  InvalidRunState,
  ObservationUnavailable,
  RunNotFound,
  RunSnapshot,
  RunStatus,
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
    self._ingestor = (
      ingestor if ingestor is not None else RunEventIngestor(store, executions)
    )

  async def start_run(self, thread_id: str, message: str) -> RunExecution:
    async def start() -> RunExecution:
      # 持久取消先释放产品槽位，但旧 Graph 必须退出后才能使用同一 checkpoint。
      for previous in self._executions.for_thread(thread_id):
        run = await self.read_run(thread_id, previous.run_id)
        if RunStatus(run["status"]).terminal and previous.task is not None:
          await asyncio.shield(asyncio.gather(previous.task, return_exceptions=True))
      run_id = uuid.uuid4().hex
      entry = HumanMessage(id=uuid.uuid4().hex, content=replace_surrogates(message))
      # todo. 这个后面都要手动到event文件里面（created生成event）
      created = await self._store.create_run(
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
          settlement=self._store,
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
        await self._store.settle_execution(
          thread_id=thread_id,
          run_id=run_id,
          outcome=ExecutionOutcome(ExecutionReason.FAILED, error=error),
        )
        raise

    return await self._accept(thread_id, start)

  async def _accept[T](
    self, thread_id: str, operation: Callable[[], Coroutine[Any, Any, T]]
  ) -> T:
    async def coordinated() -> T:
      lock = self._thread_locks.setdefault(thread_id, asyncio.Lock())
      async with lock:
        return await operation()

    return await self._lifecycle.accept(coordinated())

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
      # 这里存疑，是不是需要判断最新的那个数据是不是当前待判断的interrupt。找最后一个 approval 好像没什么用吧
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
      # 这里记录也改一下，是不是在 执行的时候？
      accepted = await self._store.accept_approval_decisions(
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
          settlement=self._store,
          initial_events=accepted.events,
          ingest_message=partial(
            self._ingestor.ingest_message, thread_id=thread_id, run_id=run_id
          ),
          ingest_delta=partial(
            self._ingestor.ingest_delta, thread_id=thread_id, run_id=run_id
          ),
        )
      except Exception as error:
        await self._store.settle_execution(
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
        result = await self._store.cancel_run(thread_id=thread_id, run_id=run_id)
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
