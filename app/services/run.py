"""产品 Run 的创建、执行协调、等待与查询。"""

import asyncio
import uuid
from functools import partial
from typing import Any

from langchain_core.messages import HumanMessage
from shikigen.execution import (
  ExecutionOutcome,
  ExecutionReason,
  ExecutionRegistry,
  RunExecution,
)
from shikigen.utils.text_safety import replace_surrogates

from app.lifecycle import ApplicationLifecycle
from app.persistence import ChatStore
from app.run_events import RunEventIngestor
from app.run_execution import start_run_execution
from app.run_observation import RunObservation
from app.run_state import (
  CommittedEvent,
  ExecutionStopped,
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
    self.agent = agent
    self._store = store
    self._executions = executions
    self._lifecycle = lifecycle
    self._ingestor = (
      ingestor if ingestor is not None else RunEventIngestor(store, executions)
    )

  async def start_run(self, thread_id: str, message: str) -> RunExecution:
    async def start() -> RunExecution:
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

    return await self._lifecycle.accept(start())

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
