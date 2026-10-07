"""事件写入、消息预览与提交后广播；运行状态变更由 runs 管理。"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from typing import Any, Literal
from weakref import WeakKeyDictionary

from shikigen.contracts.events import (
  Preview,
)
from shikigen.contracts.messages import message_identity
from shikigen.contracts.runs import (
  CommittedEvent,
  CommittedRunState,
  MessageConflict,
  RunStatus,
  RunWriteResult,
)
from shikigen.contracts.stream import MessageData
from shikigen.core.execution import (
  ExecutionRegistry,
  RunExecution,
)
from shikigen.core.stream import Stream
from shikigen.persistence import ChatStore
from shikigen.persistence.chat_store import RunTransaction

logger = logging.getLogger(__name__)


@dataclass
class _PreviewState:
  lock: asyncio.Lock = field(default_factory=asyncio.Lock)
  sequences: dict[str, int] = field(default_factory=dict)
  text: dict[str, list[str]] = field(default_factory=dict)
  committed_message_ids: set[str] = field(default_factory=set)
  sealed: bool = False


class RunEventIngestor:
  """接入事件与消息，不决定 Run 状态或审批流程。

  事务内事件写入不要求活跃 execution；消息预览使用本地执行句柄。
  广播失败不改变已经提交的业务事实。
  不提供跨进程可靠投递。观察者按事实的 id/seq 去重，通过查询补读；
  Stream 自己的 id 仅表示当前内存流顺序。
  """

  _published: WeakKeyDictionary[Stream, set[int]] = WeakKeyDictionary()
  _statuses: WeakKeyDictionary[Stream, RunStatus] = WeakKeyDictionary()

  def __init__(self, store: ChatStore, executions: ExecutionRegistry) -> None:
    self._store = store
    self._executions: ExecutionRegistry = executions
    # interrupted 或结算回滚后，正文仍由 Run 持有，不随 invocation 句柄移除。
    self._previews: dict[tuple[str, str], _PreviewState] = {}

  @staticmethod
  async def write_in_transaction(
    transaction: RunTransaction,
    thread_id: str,
    run_id: str,
    event_type: str,
    category: str,
    event_key: str,
    content: Any,
  ) -> None:
    """在调用方事务内写入事件；不提交、不广播，不要求活跃 execution。

    调用方负责生成事件内容，并将相关状态变更放在同一事务中。
    只有事务成功退出后，才能发布这些事件。
    """
    await transaction.events.insert_fact(
      thread_id, run_id, event_type, category, event_key, content
    )

  def _state(self, execution: RunExecution) -> _PreviewState:
    return self._previews.setdefault(
      (execution.thread_id, execution.run_id), _PreviewState()
    )

  async def settle(
    self,
    execution: RunExecution,
    settle_fn: Callable[[RunTransaction], Awaitable[CommittedRunState]],
    *,
    failed: bool = False,
  ) -> CommittedRunState:
    """结算与接入互斥；终态提交后封口，暂停或回滚保留缓冲。"""
    state = self._state(execution)
    async with state.lock:
      async with self._store.transaction() as transaction:
        message_events = ()
        run_snapshot = await transaction.runs.read_run(
          execution.run_id, execution.thread_id
        )
        if failed and run_snapshot is not None and run_snapshot["status"] == "running":
          message_events = await self._write_buffered_messages(
            transaction, state, execution.thread_id, execution.run_id, "error"
          )
        settlement = await settle_fn(transaction)
        settlement = replace(settlement, events=(*message_events, *settlement.events))
      if settlement.status.terminal:
        state.sealed = True
        state.text.clear()
      return settlement

  def release(self, execution: RunExecution) -> None:
    key = (execution.thread_id, execution.run_id)
    state = self._previews.get(key)
    if state is not None and state.sealed:
      self._previews.pop(key)

  async def _terminal(self, thread_id: str, run_id: str) -> bool:
    run = await self._store.get_run(run_id, thread_id)
    return run is not None and RunStatus(run["status"]).terminal

  async def ingest_delta(
    self, data: MessageData, *, thread_id: str, run_id: str
  ) -> None:
    preview = Preview.model_validate(data)
    if preview.done:
      return
    if preview.message_id is None:
      raise ValueError("Message preview requires message_id")
    execution = self._executions.get(thread_id, run_id)
    if execution is None:
      if await self._terminal(thread_id, run_id):
        return
      raise RuntimeError("Delta ingestion requires an active execution")
    state = self._state(execution)
    # todo. 检查持锁后的事件顺序与并发行为。
    async with state.lock:
      if state.sealed:
        return
      if preview.message_id in state.committed_message_ids:
        raise MessageConflict("Delta received after complete message was committed")
      seq = state.sequences.get(preview.message_id)
      if seq is None:
        seq = await self._store.reserve_message_sequence(
          thread_id=thread_id, run_id=run_id, message_id=preview.message_id
        )
        state.sequences[preview.message_id] = seq
      state.text.setdefault(preview.message_id, []).append(preview.text)
      execution.stream.publish(
        "message",
        {
          "message_id": preview.message_id,
          "seq": seq,
          "text": preview.text,
          "done": False,
        },
      )

  async def append_event(
    self,
    *,
    thread_id: str,
    run_id: str,
    event_type: str,
    category: str,
    content: Any,
    metadata: dict[str, Any] | None = None,
    event_key: str | None = None,
  ) -> int:
    execution = self._executions.get(thread_id, run_id)
    if execution is None:
      if await self._terminal(thread_id, run_id):
        return 0
      raise RuntimeError("Message ingestion requires an active execution")
    state = self._state(execution)
    async with state.lock:
      if state.sealed:
        return state.sequences.get(content.get("message_id"), 0)
      if category == "message" and content["type"] == "ai":
        existing = await self._store.get_message(thread_id, event_key or "")
        if (
          existing is not None
          and existing["content"].get("generation_status", "complete") != "complete"
        ):
          # 根 Graph 后续重放不得覆盖封存正文或把它归给下一 Run。
          return existing["seq"]
      if (
        category == "message"
        and content["type"] == "tool"
        and "artifact" in content
        and content["artifact"] is None
      ):
        existing = await self._store.get_message(thread_id, event_key or "")
        if existing is not None and "artifact" not in existing["content"]:
          # checkpoint 反序列化会把 ToolMessage 的默认 artifact=None 标成已提供。
          # 重放沿用已提交事实的字段存在性；其余内容仍交给存储严格校验。
          content = {key: value for key, value in content.items() if key != "artifact"}
      result = await self._store.append_committed_event(
        thread_id=thread_id,
        run_id=run_id,
        event_type=event_type,
        category=category,
        content=content,
        metadata=metadata,
        event_key=event_key,
      )
      if category == "message" and result.event["content"]["type"] == "ai":
        message = result.event["content"]
        identity = message["message_id"]
        state.committed_message_ids.add(identity)
        preview = state.text.pop(identity, None)
        if preview is not None and isinstance(message["content"], str):
          if "".join(preview) != message["content"]:
            logger.warning(
              "Complete message differs from preview: %s/%s/%s",
              thread_id,
              run_id,
              identity,
            )
      if result.inserted and result.event["run_id"] == run_id:
        self.publish(execution.stream, (result.event,))
      return result.event["seq"]

  async def cancel(
    self,
    thread_id: str,
    run_id: str,
    cancel_fn: Callable[[RunTransaction], Awaitable[RunWriteResult]],
  ) -> RunWriteResult:
    """冻结接入直到事务结束；失败保留缓冲，成功后封口。"""
    execution = self._executions.get(thread_id, run_id)
    # 首事件尚未接入时也要先建立锁，避免事务等待间隙创建未封口缓冲。
    state = self._previews.setdefault((thread_id, run_id), _PreviewState())
    async with state.lock:
      async with self._store.transaction() as transaction:
        message_events = ()
        run_snapshot = await transaction.runs.read_run(run_id, thread_id)
        if run_snapshot is not None and not RunStatus(run_snapshot["status"]).terminal:
          message_events = await self._write_buffered_messages(
            transaction, state, thread_id, run_id, "cancelled"
          )
        cancellation = await cancel_fn(transaction)
        cancellation = replace(
          cancellation, events=(*message_events, *cancellation.events)
        )
      if RunStatus(cancellation.run["status"]).terminal:
        state.sealed = True
        state.text.clear()
        if execution is None:
          self._previews.pop((thread_id, run_id), None)
      return cancellation

  @staticmethod
  async def _write_buffered_messages(
    transaction: RunTransaction,
    state: _PreviewState,
    thread_id: str,
    run_id: str,
    generation_status: Literal["error", "cancelled"],
  ) -> tuple[CommittedEvent, ...]:
    """把尚未提交的非空正文转为规范消息，复用普通消息的事务内写入。"""
    message_events = []
    for identity, parts in state.text.items():
      text = "".join(parts)
      if identity in state.committed_message_ids or not text:
        continue
      if await transaction.events.message_by_key(thread_id, f"ai:{identity}"):
        continue  # 已提交的完整或中止消息保留原事实。
      message = {
        "type": "ai",
        "message_id": identity,
        "content": text,
        "tool_calls": [],
        "generation_status": generation_status,
      }
      write_result = await transaction.events.write_message_in_transaction(
        thread_id=thread_id, run_id=run_id, message=message
      )
      if write_result.inserted:
        message_events.append(write_result.event)
    return tuple(message_events)

  async def ingest_message(
    self, content: dict[str, Any], *, thread_id: str, run_id: str
  ) -> int:
    event_type, event_key = message_identity(content)
    return await self.append_event(
      thread_id=thread_id,
      run_id=run_id,
      content=content,
      event_type=event_type,
      event_key=event_key,
      category="message",
    )

  @staticmethod
  def publish(
    stream: Stream,
    events: tuple[CommittedEvent, ...],
    *,
    settlement: CommittedRunState | None = None,
  ) -> None:
    """唯一事实发布入口；简化终态事件保留为现有传输的兼容投影。"""
    try:
      published = RunEventIngestor._published.setdefault(stream, set())
      for event in events:
        if event["id"] not in published:
          stream.publish("durable_event", event)
          published.add(event["id"])
      if (
        settlement is not None
        and RunEventIngestor._statuses.get(stream) != settlement.status
      ):
        RunEventIngestor._statuses[stream] = settlement.status
        if settlement.status is RunStatus.ERROR:
          stream.publish("error", {"message": settlement.error or "Run failed"})
        elif settlement.status is RunStatus.COMPLETED:
          stream.publish("status", {"status": "completed"})
        elif settlement.status is RunStatus.CANCELLED:
          stream.publish("status", {"status": "cancelled"})
        elif settlement.status is RunStatus.INTERRUPTED:
          stream.publish("status", {"status": "interrupted"})
    except Exception:
      logger.exception(
        "Committed facts could not be published; recover via list_run_events: %s",
        [(event["thread_id"], event["run_id"], event["seq"]) for event in events],
      )
      RunEventIngestor.notify_failure(stream, "event_publication_failed")

  @staticmethod
  def notify_failure(stream: Stream, code: str) -> None:
    # 广播可能整体失效；通知不能覆盖原存储异常或污染 Graph 结果。
    try:
      stream.publish("stream_failed", {"code": code})
    except Exception:
      logger.exception(
        "Observation failure notification could not be published: %s", code
      )
