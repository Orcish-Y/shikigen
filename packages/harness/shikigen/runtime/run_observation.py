"""只读观察流：封装单次本地执行、已终态持久历史或“持久前缀 + 当前执行流”，
统一提供事件迭代与生命周期管理。
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, AsyncIterator
from typing import NotRequired, Protocol, TypedDict

from shikigen.contracts.runs import CommittedEvent, RunSnapshot
from shikigen.contracts.stream import StreamEvent, StreamEventVariant, UsageData
from shikigen.core.execution import RunExecution
from shikigen.persistence import ChatStore


class ObservationMetadata(TypedDict):
  """观察建立时捕获的 Run 初始元数据快照。

  直接从本地执行构建时初始状态置为 running；从存储重建时同步持久快照的状态与用量。
  """

  thread_id: str
  run_id: str
  status: str
  usage: NotRequired[UsageData | None]
  usage_pending: NotRequired[bool]


class Subscription(Protocol):
  """事件订阅协议，抽象底层 Stream 订阅对象的异步迭代与关闭行为。"""

  def __aiter__(self) -> AsyncIterator[StreamEventVariant]: ...
  async def __anext__(self) -> StreamEventVariant: ...
  async def aclose(self) -> None: ...


class RunObservation:
  """只读事件观察流（异步迭代器）。

  调用者负责通过 aclose 释放资源（底层订阅与迭代器生成器，支持幂等关闭）。
  """

  def __init__(
    self,
    metadata: ObservationMetadata,
    history: list[CommittedEvent],
    subscription: Subscription | None = None,
  ) -> None:
    self.metadata = metadata
    self._subscription = subscription
    self._iterator = self._events(history)
    self._closed = False

  @classmethod
  def from_execution(cls, execution: RunExecution) -> RunObservation:
    """直接观察指定本地执行（RunExecution）的内存缓存与后续实时事件，不访问注册表与存储。

    即使执行已收尾并移出注册表，传入的执行对象仍保留本次执行的完整事件缓存。
    构建时已同步注册底层订阅；返回后无论是否开始迭代，调用者均须调用 aclose 释放订阅。
    """
    return cls(
      {
        "thread_id": execution.thread_id,
        "run_id": execution.run_id,
        "status": "running",
      },
      [],
      execution.stream.subscribe(),
    )

  @classmethod
  async def rebuild(
    cls,
    run: RunSnapshot,
    *,
    store: ChatStore,
    execution: RunExecution | None = None,
  ) -> RunObservation:
    """从存储重建观察流；若存在活跃执行，则串联“持久前缀 + 实时执行流”。

    若有活跃执行，先建立实时订阅以避免读取存储期间丢失后续事件，再截取持久化事件中
    seq < replay_start_seq 的前缀事实。Run 与 execution 的一致性由 RunService 前置校验；
    数据库查询时的 MAX(seq) 不是提交水位，必须以 execution.replay_start_seq 作为分界。
    """
    subscription = execution.stream.subscribe() if execution is not None else None
    try:
      history = await store.list_run_events(run["thread_id"], run["id"])
      if execution is not None:
        history = [e for e in history if e["seq"] < execution.replay_start_seq]
      return cls(
        {
          "thread_id": run["thread_id"],
          "run_id": run["id"],
          "status": run["status"],
          "usage": run["usage"],
          "usage_pending": run["usage_pending"],
        },
        history,
        subscription,
      )
    except BaseException:
      if subscription is not None:
        await subscription.aclose()
      raise

  def __aiter__(self) -> RunObservation:
    return self

  async def __anext__(self) -> StreamEventVariant:
    if self._closed:
      raise StopAsyncIteration
    return await anext(self._iterator)

  async def _events(
    self, history: list[CommittedEvent]
  ) -> AsyncGenerator[StreamEventVariant, None]:
    """串联持久历史事实与实时事件流；生成器退出时负责释放底层订阅。"""
    try:
      for fact in history:
        yield StreamEvent(id="", event="durable_event", data=fact)
      if self._subscription is not None:
        async for event in self._subscription:
          yield event
    finally:
      if self._subscription is not None:
        await self._subscription.aclose()

  async def aclose(self) -> None:
    """释放观察流持有的全部资源（幂等）。显式关闭底层订阅与异步迭代器。"""
    if self._closed:
      return
    self._closed = True
    # 异步生成器从未被迭代时，aclose 不会进入其内部 finally；
    # 此处须显式关闭底层订阅，防止订阅队列泄漏。
    if self._subscription is not None:
      await self._subscription.aclose()
      self._subscription = None
    await self._iterator.aclose()
