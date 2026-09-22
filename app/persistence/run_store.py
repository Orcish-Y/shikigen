"""运行的创建、状态结算及查询；跨表变更在这里统一提交。"""

import json
from collections.abc import Awaitable, Callable
from typing import Any

import aiosqlite
from langchain_core.messages import HumanMessage
from shikigen.event_contract import (
  ApprovalInvalidated,
  ApprovalRequired,
  ApprovalResolved,
  ApprovalSubmission,
  Usage,
)
from shikigen.execution import ExecutionOutcome, ExecutionReason
from shikigen.stream import UsageData

from app.approval import validate_responses
from app.persistence.database import Database, _now, integrity_error
from app.persistence.event_store import EventStore
from app.run_state import (
  AcceptedApproval,
  ApprovalConflict,
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
    invocation_seq: int | None = None,
    usage: UsageData | None = None,
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
        history = await self._events.read_events(thread_id, run_id)
        running = next(e for e in reversed(history) if e["event_type"] == "run_running")
        if invocation_seq is not None and invocation_seq != running["seq"]:
          raise InvalidRunState(
            "A stale invocation cannot settle the current execution"
          )
        if usage is not None:
          validated = Usage.model_validate(usage).model_dump(mode="json")
          cursor = await self._db.connection.execute(
            "SELECT usage_json FROM run_usage WHERE thread_id = ? AND run_id = ? "
            "AND invocation_seq = ?",
            (thread_id, run_id, running["seq"]),
          )
          previous = await cursor.fetchone()
          if previous is not None and json.loads(previous["usage_json"]) != validated:
            raise InvalidRunState("Invocation usage conflicts with its settled usage")
          if previous is None:
            await self._db.connection.execute(
              "INSERT INTO run_usage VALUES (?, ?, ?, ?)",
              (thread_id, run_id, running["seq"], json.dumps(validated)),
            )
        total_usage, _ = await self._usage(run_id, thread_id)
        settlement_key = f"settled:{run_id}:{running['seq']}"
        if row["status"] != RunStatus.RUNNING:
          event = None
          if row["status"] == RunStatus.CANCELLED:
            event = await self._events.event_by_key(
              thread_id, run_id, f"cancelled:{run_id}"
            )
          if event is None:
            event = await self._events.event_by_key(thread_id, run_id, settlement_key)
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
        events = []
        if approval is not None:
          key = f"approval:required:{approval.checkpoint.configurable.checkpoint_id}"
          await write_fact(
            thread_id,
            run_id,
            "approval_required",
            "approval",
            key,
            approval.model_dump(mode="json"),
          )
          required = await self._events.event_by_key(thread_id, run_id, key)
          assert required is not None
          events.append(required)
        await write_fact(
          thread_id,
          run_id,
          f"run_{target}",
          "lifecycle",
          settlement_key,
          content,
        )
        await self._db.connection.execute(
          "UPDATE threads SET updated_at = ? WHERE id = ?", (now, thread_id)
        )
        event = await self._events.event_by_key(thread_id, run_id, settlement_key)
        assert event is not None
        await self._db.connection.commit()
        return CommittedRunState(
          target, error, error_code, (*events, event), usage=total_usage
        )
      except aiosqlite.IntegrityError as error:
        await self._db.connection.rollback()
        raise integrity_error(error) from error
      except BaseException:
        await self._db.connection.rollback()
        raise

  async def cancel_run(
    self,
    *,
    thread_id: str,
    run_id: str,
    fact_writer: Callable[..., Awaitable[None]] | None = None,
  ) -> RunWriteResult:
    """原子取消运行或暂停；终态幂等返回，不覆盖第一次有效提交。"""
    write_fact = fact_writer or self._events.insert_fact
    async with self._db.lock:
      try:
        await self._db.connection.execute("BEGIN IMMEDIATE")
        run = await self._get_run(run_id, thread_id)
        if run is None:
          raise RunNotFound("Run not found")
        if RunStatus(run["status"]).terminal:
          await self._db.connection.commit()
          return RunWriteResult(run, ())
        history = await self._events.read_events(thread_id, run_id)
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
          await write_fact(
            thread_id,
            run_id,
            "approval_invalidated",
            "approval",
            key,
            invalidated.model_dump(mode="json"),
          )
          keys.append(key)
        key = f"cancelled:{run_id}"
        await write_fact(
          thread_id, run_id, "run_cancelled", "lifecycle", key, {"status": "cancelled"}
        )
        keys.append(key)
        now = _now()
        await self._db.connection.execute(
          "UPDATE runs SET status = 'cancelled', error = NULL, error_code = NULL, "
          "updated_at = ?, completed_at = ? WHERE id = ? AND thread_id = ?",
          (now, now, run_id, thread_id),
        )
        await self._db.connection.execute(
          "UPDATE threads SET updated_at = ? WHERE id = ?", (now, thread_id)
        )
        updated = await self._get_run(run_id, thread_id)
        assert updated is not None
        events = []
        for key in keys:
          event = await self._events.event_by_key(thread_id, run_id, key)
          assert event is not None
          events.append(event)
        await self._db.connection.commit()
        return RunWriteResult(updated, tuple(events))
      except BaseException:
        await self._db.connection.rollback()
        raise

  async def accept_approval_decisions(
    self,
    *,
    thread_id: str,
    run_id: str,
    submission: ApprovalSubmission,
    fact_writer: Callable[..., Awaitable[None]] | None = None,
  ) -> AcceptedApproval:
    """串行检查当前暂停，原子保存响应与 running；不调用 Graph。"""
    write_fact = fact_writer or self._events.insert_fact
    async with self._db.lock:
      try:
        await self._db.connection.execute("BEGIN IMMEDIATE")
        run = await self._get_run(run_id, thread_id)
        if run is None:
          raise RunNotFound("Run not found")
        if run["status"] != RunStatus.INTERRUPTED:
          raise ApprovalConflict("Run is not waiting for approval; read current facts")
        history = await self._events.read_events(thread_id, run_id)
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
        await write_fact(
          thread_id,
          run_id,
          "approval_resolved",
          "approval",
          resolved_key,
          resolved.model_dump(mode="json", exclude_none=True),
        )
        await write_fact(
          thread_id,
          run_id,
          "run_running",
          "lifecycle",
          running_key,
          {"status": "running"},
        )
        now = _now()
        await self._db.connection.execute(
          """UPDATE runs SET status = 'running', error = NULL, error_code = NULL,
          completed_at = NULL, updated_at = ? WHERE id = ? AND thread_id = ?""",
          (now, run_id, thread_id),
        )
        await self._db.connection.execute(
          "UPDATE threads SET updated_at = ? WHERE id = ?", (now, thread_id)
        )
        resolved_event = await self._events.event_by_key(
          thread_id, run_id, resolved_key
        )
        running_event = await self._events.event_by_key(thread_id, run_id, running_key)
        assert resolved_event is not None and running_event is not None
        await self._db.connection.commit()
        return AcceptedApproval(
          required.checkpoint.model_dump(mode="json"),
          resume,
          (resolved_event, running_event),
        )
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
    usage, pending = await self._usage(run_id, thread_id)
    return RunSnapshot(
      id=row["id"],
      thread_id=row["thread_id"],
      status=row["status"],
      error=row["error"],
      error_code=row["error_code"],
      created_at=row["created_at"],
      updated_at=row["updated_at"],
      completed_at=row["completed_at"],
      usage=usage,
      usage_pending=pending,
    )

  async def _usage(self, run_id: str, thread_id: str) -> tuple[UsageData | None, bool]:
    """调用方持有数据库锁；没有结算记录时返回未知，而非零消耗。"""
    cursor = await self._db.connection.execute(
      "SELECT usage_json FROM run_usage WHERE run_id = ? AND thread_id = ?",
      (run_id, thread_id),
    )
    rows = await cursor.fetchall()
    total: UsageData | None = None
    if rows:
      total = {
        "total_input": 0,
        "total_output": 0,
        "total_tokens": 0,
        "calls": 0,
        "by_model": {},
      }
      for row in rows:
        usage = json.loads(row["usage_json"])
        total["total_input"] += usage["total_input"]
        total["total_output"] += usage["total_output"]
        total["total_tokens"] += usage["total_tokens"]
        total["calls"] += usage["calls"]
        for model, data in usage["by_model"].items():
          entry = total["by_model"].setdefault(
            model, {"input": 0, "output": 0, "calls": 0}
          )
          entry["input"] += data["input"]
          entry["output"] += data["output"]
          entry["calls"] += data["calls"]
    cursor = await self._db.connection.execute(
      "SELECT 1 FROM run_events e WHERE e.run_id = ? AND e.thread_id = ? "
      "AND e.event_type = 'run_running' AND NOT EXISTS ("
      "SELECT 1 FROM run_usage u WHERE u.run_id = e.run_id "
      "AND u.thread_id = e.thread_id AND u.invocation_seq = e.seq) LIMIT 1",
      (run_id, thread_id),
    )
    return total, await cursor.fetchone() is not None
