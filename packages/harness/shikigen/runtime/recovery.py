"""单进程启动协调：恢复持久状态，不自动重放 Graph 或工具。"""

import asyncio
import json
import logging
import sqlite3
from typing import TYPE_CHECKING, Any

from shikigen.contracts.events import ApprovalRequired
from shikigen.contracts.runs import (
  RecoveryUnavailable,
  RunNotFound,
  RunSnapshot,
  RunStatus,
)
from shikigen.core.execution import ExecutionRegistry
from shikigen.core.graph_pause import GraphPauseCollector, InvalidCheckpoint
from shikigen.persistence import ChatStore

if TYPE_CHECKING:
  from shikigen.runtime.runs import RunTransitions

logger = logging.getLogger(__name__)


def _temporary_storage_error(error: Exception) -> bool:
  if isinstance(error, OSError):
    return True
  if isinstance(error, sqlite3.OperationalError):
    # 扩展错误码的低 8 位是主错误码；SQL/表结构错误不能靠重试解决。
    return getattr(error, "sqlite_errorcode", 0) & 0xFF in {
      sqlite3.SQLITE_BUSY,
      sqlite3.SQLITE_LOCKED,
      sqlite3.SQLITE_IOERR,
      sqlite3.SQLITE_CANTOPEN,
      sqlite3.SQLITE_FULL,
      sqlite3.SQLITE_READONLY,
    }
  return False


class RunRecoveryCoordinator:
  """启动扫描在接收操作前调用；运行中校验由 RunService 的 Thread 锁串行化。

  已读数据解码失败或结构矛盾属于损坏。存储 I/O、锁等可恢复故障保留原状态，
  启动时重试；请求时抛 RecoveryUnavailable。其他异常保留堆栈并原样传播。
  """

  def __init__(
    self,
    *,
    agent: Any,
    store: ChatStore,
    executions: ExecutionRegistry,
    transitions: "RunTransitions",
  ) -> None:
    self._agent = agent
    self._store = store
    self._executions = executions
    self._transitions = transitions

  async def reconcile_all(self, *, retry_delay: float = 1.0) -> None:
    """每轮继续检查其他 Run；依赖故障延迟重试，取消直接传播。"""
    while True:
      retry = False
      try:
        runs = await self._store.list_nonterminal_runs()
      except Exception as error:
        if not _temporary_storage_error(error):
          logger.exception("recovery_scan_failed")
          raise
        logger.warning(
          "recovery_scan_unavailable error_type=%s", type(error).__name__, exc_info=True
        )
        runs, retry = [], True
      for run in runs:
        try:
          await self.reconcile_run(run["thread_id"], run["id"])
        except RecoveryUnavailable:
          retry = True
      if not retry:
        return
      logger.warning("recovery_retry delay=%s", retry_delay)
      await asyncio.sleep(retry_delay)

  async def reconcile_run(self, thread_id: str, run_id: str) -> RunSnapshot:
    try:
      return await self._reconcile_run(thread_id, run_id)
    except RunNotFound:
      raise
    except Exception as error:
      if not _temporary_storage_error(error):
        logger.exception("recovery_failed thread_id=%s run_id=%s", thread_id, run_id)
        raise
      logger.warning(
        "recovery_unavailable thread_id=%s run_id=%s error_type=%s",
        thread_id,
        run_id,
        type(error).__name__,
        exc_info=True,
      )
      raise RecoveryUnavailable("Run recovery unavailable; retry later") from error

  async def _reconcile_run(self, thread_id: str, run_id: str) -> RunSnapshot:
    run = await self._store.get_run(run_id, thread_id)
    if run is None:
      raise RunNotFound("Run not found")
    if RunStatus(run["status"]).terminal:
      return run
    if run["status"] == "running":
      if self._executions.get(thread_id, run_id) is not None:
        return run
      code, message = "invocation_lost", "Local execution was lost before settlement"
    else:
      # JSON 解码失败表示已读数据损坏；I/O 异常交给外层保留状态并重试。
      try:
        history = await self._store.list_run_events(thread_id, run_id)
      except json.JSONDecodeError:
        logger.warning(
          "approval_fact_corrupt thread_id=%s run_id=%s",
          thread_id,
          run_id,
          exc_info=True,
        )
        history = []
      try:
        pending = next(
          (e for e in reversed(history) if e["category"] == "approval"), None
        )
        if pending is None or pending["event_type"] != "approval_required":
          raise ValueError("Missing pending approval")
        required = ApprovalRequired.model_validate(pending["content"])
        coordinate = required.checkpoint.configurable
        if coordinate.thread_id != thread_id or coordinate.checkpoint_ns:
          raise ValueError("Foreign approval checkpoint")
        lifecycle = next(
          (e for e in reversed(history) if e["category"] == "lifecycle"), None
        )
        if (
          lifecycle is None
          or lifecycle["event_type"] != "run_interrupted"
          or lifecycle["seq"] <= pending["seq"]
        ):
          raise ValueError("Missing matching interruption fact")
      except ValueError:
        required = None
      valid = False
      if required is not None:
        collector = GraphPauseCollector(thread_id)
        collector.checkpoint = required.checkpoint.model_dump(mode="json")
        try:
          pause = await collector.read_pause(self._agent)
        except (InvalidCheckpoint, json.JSONDecodeError):
          logger.warning(
            "approval_checkpoint_corrupt thread_id=%s run_id=%s",
            thread_id,
            run_id,
            exc_info=True,
          )
          pause = None
        valid = pause is not None and (
          {item["id"]: item for item in pause.interrupts}
          == {item.id: item.model_dump(mode="json") for item in required.interrupts}
        )
      if valid:
        return run
      code, message = (
        "approval_state_corrupt",
        "Persisted approval does not match its checkpoint",
      )
    updated = await self._transitions.fail_recovery(run, code, message)
    logger.warning("%s thread_id=%s run_id=%s", code, thread_id, run_id)
    return updated
