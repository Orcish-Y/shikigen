"""应用层的持久事实接入：先提交，再广播存储返回的完整事件。"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any
from weakref import WeakKeyDictionary

from shikigen.event_contract import Preview
from shikigen.execution import ExecutionRegistry, RunExecution
from shikigen.stream import MessageData, Stream

from app.persistence import ChatStore
from app.run_state import CommittedEvent, CommittedRunState, MessageConflict, RunStatus

logger = logging.getLogger(__name__)


@dataclass
class _PreviewState:
  lock: asyncio.Lock = field(default_factory=asyncio.Lock)
  sequences: dict[str, int] = field(default_factory=dict)
  text: dict[str, list[str]] = field(default_factory=dict)
  committed: set[str] = field(default_factory=set)


class RunEventIngestor:
  """供执行事件消费入口注入；广播失败不改变已经提交的业务事实。

  不提供跨进程可靠投递。观察者按事实的 id/seq 去重，通过查询补读；
  Stream 自己的 id 仅表示当前内存流顺序。
  """

  _published: WeakKeyDictionary[Stream, set[int]] = WeakKeyDictionary()
  _statuses: WeakKeyDictionary[Stream, RunStatus] = WeakKeyDictionary()

  def __init__(self, store: ChatStore, executions: ExecutionRegistry) -> None:
    self._store = store
    self._executions: ExecutionRegistry = executions
    self._previews: WeakKeyDictionary[RunExecution, _PreviewState] = WeakKeyDictionary()

  def _state(self, execution: RunExecution) -> _PreviewState:
    return self._previews.setdefault(execution, _PreviewState())

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
      raise RuntimeError("Delta ingestion requires an active execution")
    state = self._state(execution)
    # todo. 检查持锁后的事件顺序与并发行为。
    async with state.lock:
      if preview.message_id in state.committed:
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
      raise RuntimeError("Message ingestion requires an active execution")
    state = self._state(execution)
    async with state.lock:
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
        state.committed.add(identity)
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

  async def ingest_message(
    self, content: dict[str, Any], *, thread_id: str, run_id: str
  ) -> int:
    from shikigen.messages import message_identity

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
