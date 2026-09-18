"""运行的创建、状态结算及查询；跨表变更在这里统一提交。"""

from collections.abc import Awaitable, Callable
from typing import Any

import aiosqlite
from langchain_core.messages import HumanMessage
from shikigen.execution import ExecutionOutcome, ExecutionReason

from app.persistence.database import Database, _now, integrity_error
from app.persistence.event_store import EventStore
from app.run_state import (
  CommittedRunState,
  InvalidRunState,
  MessageConflict,
  RunNotFound,
  RunSnapshot,
  RunStatus,
  RunWriteResult,
  ThreadBusy,
  ThreadNotFound,
)


class RunStore:
  def __init__(self, database: Database, events: EventStore):
    self._db = database
    self._events = events

  async def create_run(
    self,
    *,
    run_id: str,
    thread_id: str,
    entry_message: HumanMessage,
    fact_writer: Callable[..., Awaitable[None]] | None = None,
  ) -> RunWriteResult:
    """在一个写事务中检查排他并提交 Run、running 事实和入口消息。

    BEGIN IMMEDIATE 使本接口在多个连接间也串行检查。
    新库有 schema 排他约束；数据库必须使用当前 schema。
    """
    self._events.message_identity(
      {
        "type": "human",
        "content": entry_message.content,
        "message_id": entry_message.id,
      }
    )
    write_fact = fact_writer or self._events.insert_fact
    async with self._db.lock:
      try:
        await self._db.connection.execute("BEGIN IMMEDIATE")
        cursor = await self._db.connection.execute(
          "SELECT 1 FROM threads WHERE id = ?", (thread_id,)
        )
        if await cursor.fetchone() is None:
          raise ThreadNotFound("Thread not found")
        cursor = await self._db.connection.execute(
          """
          SELECT 1 FROM runs WHERE thread_id = ?
          AND status NOT IN ('completed', 'error', 'cancelled') LIMIT 1
          """,
          (thread_id,),
        )
        if await cursor.fetchone() is not None:
          raise ThreadBusy("Thread is busy with another run")
        if await self._events.message_by_key(thread_id, f"human:{entry_message.id}"):
          raise MessageConflict("Entry message already belongs to a run")
        now = _now()
        await self._db.connection.execute(
          """INSERT INTO runs(id, thread_id, status, created_at, updated_at)
          VALUES (?, ?, 'running', ?, ?)""",
          (run_id, thread_id, now, now),
        )
        await write_fact(
          thread_id,
          run_id,
          "run_running",
          "lifecycle",
          f"running:{run_id}",
          {"status": "running"},
        )
        await write_fact(
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
        await self._db.connection.execute(
          "UPDATE threads SET updated_at = ? WHERE id = ?", (now, thread_id)
        )
        run = await self._get_run(run_id, thread_id)
        assert run is not None
        events = await self._events.read_events(thread_id, run_id)
        await self._db.connection.commit()
        return RunWriteResult(run, tuple(events))
      except aiosqlite.IntegrityError as error:
        await self._db.connection.rollback()
        raise integrity_error(error) from error
      except BaseException:
        await self._db.connection.rollback()
        raise

  async def settle_execution(
    self,
    *,
    thread_id: str,
    run_id: str,
    outcome: ExecutionOutcome,
    error_code: str | None = None,
    fact_writer: Callable[..., Awaitable[None]] | None = None,
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
    write_fact = fact_writer or self._events.insert_fact
    async with self._db.lock:
      try:
        await self._db.connection.execute("BEGIN IMMEDIATE")
        cursor = await self._db.connection.execute(
          "SELECT status, error, error_code FROM runs WHERE id = ? AND thread_id = ?",
          (run_id, thread_id),
        )
        row = await cursor.fetchone()
        if row is None:
          raise RunNotFound("Run not found")
        if row["status"] != RunStatus.RUNNING:
          event = await self._events.event_by_key(
            thread_id, run_id, f"settled:{run_id}"
          )
          if event is None or event["content"].get("status") != row["status"]:
            raise InvalidRunState("Run is missing its matching settlement fact")
          committed = CommittedRunState(
            RunStatus(row["status"]),
            row["error"],
            row["error_code"],
            (event,),
            changed=False,
          )
          await self._db.connection.commit()
          return committed
        now = _now()
        cursor = await self._db.connection.execute(
          """UPDATE runs SET status = ?, error = ?, error_code = ?,
          updated_at = ?, completed_at = ?
          WHERE id = ? AND thread_id = ? AND status = 'running'""",
          (
            target,
            error,
            error_code,
            now,
            now if target.terminal else None,
            run_id,
            thread_id,
          ),
        )
        if cursor.rowcount != 1:
          raise RuntimeError("Run state changed during settlement")
        content: dict[str, Any] = {"status": target}
        if error is not None:
          content["message"] = error
          content["error_code"] = error_code
        if outcome.pause is not None:
          content["checkpoint"] = outcome.pause.checkpoint
          content["interrupts"] = outcome.pause.interrupts
        await write_fact(
          thread_id,
          run_id,
          f"run_{target}",
          "lifecycle",
          f"settled:{run_id}",
          content,
        )
        await self._db.connection.execute(
          "UPDATE threads SET updated_at = ? WHERE id = ?", (now, thread_id)
        )
        event = await self._events.event_by_key(thread_id, run_id, f"settled:{run_id}")
        assert event is not None
        await self._db.connection.commit()
        return CommittedRunState(target, error, error_code, (event,))
      except aiosqlite.IntegrityError as error:
        await self._db.connection.rollback()
        raise integrity_error(error) from error
      except BaseException:
        await self._db.connection.rollback()
        raise

  async def get_run(self, run_id: str, thread_id: str) -> RunSnapshot | None:
    # 同一连接的读也必须等写事务结束，不能把尚未提交的状态暴露出去。
    async with self._db.lock:
      return await self._get_run(run_id, thread_id)

  async def _get_run(self, run_id: str, thread_id: str) -> RunSnapshot | None:
    cursor = await self._db.connection.execute(
      """
      SELECT id, thread_id, status, error, error_code,
             created_at, updated_at, completed_at
      FROM runs
      WHERE id = ? AND thread_id = ?
      """,
      (run_id, thread_id),
    )
    row = await cursor.fetchone()
    if row is None:
      return None
    return RunSnapshot(
      id=row["id"],
      thread_id=row["thread_id"],
      status=row["status"],
      error=row["error"],
      error_code=row["error_code"],
      created_at=row["created_at"],
      updated_at=row["updated_at"],
      completed_at=row["completed_at"],
    )
