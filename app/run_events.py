"""应用层的持久事实接入：先提交，再广播存储返回的完整事件。"""

import logging
from typing import Any

from shikigen.execution import ExecutionRegistry
from shikigen.stream import Stream

from app.persistence import ChatStore
from app.run_state import CommittedEvent, CommittedRunState, RunStatus

logger = logging.getLogger(__name__)


class RunEventIngestor:
  """供执行 middleware 注入；广播失败不改变已经提交的业务事实。

  不提供跨进程可靠投递。观察者按事实的 id/seq 去重，通过查询补读；
  Stream 自己的 id 仅表示当前内存流顺序。
  """

  def __init__(self, store: ChatStore, executions: ExecutionRegistry) -> None:
    self._store = store
    self._executions = executions

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
    result = await self._store.append_committed_event(
      thread_id=thread_id,
      run_id=run_id,
      event_type=event_type,
      category=category,
      content=content,
      metadata=metadata,
      event_key=event_key,
    )
    self.publish(execution.stream, (result.event,))
    return result.event["seq"]

  @staticmethod
  def publish(
    stream: Stream,
    events: tuple[CommittedEvent, ...],
    *,
    settlement: CommittedRunState | None = None,
  ) -> None:
    """唯一事实发布入口；简化终态事件保留为现有传输的兼容投影。"""
    try:
      for event in events:
        stream.publish("durable_event", event)
      if settlement is not None:
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
