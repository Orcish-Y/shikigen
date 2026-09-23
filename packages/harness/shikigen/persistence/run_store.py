"""Run 的 SQL 存取；写方法及 read_* 方法仅供持锁事务调用。"""

import json

from shikigen.contracts.runs import (
  RunSnapshot,
)
from shikigen.contracts.stream import UsageData
from shikigen.persistence.database import Database, _now


class RunStore:
  def __init__(self, database: Database):
    self._db = database

  async def thread_exists(self, thread_id: str) -> bool:
    cursor = await self._db.connection.execute(
      "SELECT 1 FROM threads WHERE id = ?", (thread_id,)
    )
    return await cursor.fetchone() is not None

  async def has_active_run(self, thread_id: str) -> bool:
    cursor = await self._db.connection.execute(
      "SELECT 1 FROM runs WHERE thread_id = ? "
      "AND status NOT IN ('completed', 'error', 'cancelled') LIMIT 1",
      (thread_id,),
    )
    return await cursor.fetchone() is not None

  async def insert_run(self, run_id: str, thread_id: str, status: str) -> None:
    now = _now()
    await self._db.connection.execute(
      "INSERT INTO runs(id, thread_id, status, created_at, updated_at) "
      "VALUES (?, ?, ?, ?, ?)",
      (run_id, thread_id, status, now, now),
    )

  async def touch_thread(self, thread_id: str) -> None:
    await self._db.connection.execute(
      "UPDATE threads SET updated_at = ? WHERE id = ?", (_now(), thread_id)
    )

  async def update_state(
    self,
    run_id: str,
    thread_id: str,
    *,
    status: str,
    terminal: bool,
    error: str | None = None,
    error_code: str | None = None,
    expected_status: str | None = None,
  ) -> bool:
    now = _now()
    cursor = await self._db.connection.execute(
      "UPDATE runs SET status = ?, error = ?, error_code = ?, updated_at = ?, "
      "completed_at = ? WHERE id = ? AND thread_id = ? "
      "AND (? IS NULL OR status = ?)",
      (
        status,
        error,
        error_code,
        now,
        now if terminal else None,
        run_id,
        thread_id,
        expected_status,
        expected_status,
      ),
    )
    return cursor.rowcount == 1

  async def read_invocation_usage(
    self,
    thread_id: str,
    run_id: str,
    invocation_seq: int,
  ) -> UsageData | None:
    cursor = await self._db.connection.execute(
      "SELECT usage_json FROM run_usage WHERE thread_id = ? AND run_id = ? "
      "AND invocation_seq = ?",
      (thread_id, run_id, invocation_seq),
    )
    row = await cursor.fetchone()
    return json.loads(row["usage_json"]) if row is not None else None

  async def insert_usage(
    self,
    thread_id: str,
    run_id: str,
    invocation_seq: int,
    usage: UsageData,
  ) -> None:
    await self._db.connection.execute(
      "INSERT INTO run_usage(thread_id, run_id, invocation_seq, usage_json) "
      "VALUES (?, ?, ?, ?)",
      (thread_id, run_id, invocation_seq, json.dumps(usage)),
    )

  async def list_nonterminal_runs(self) -> list[RunSnapshot]:
    async with self._db.lock:
      cursor = await self._db.connection.execute(
        "SELECT id, thread_id FROM runs WHERE status IN ('running', 'interrupted') "
        "ORDER BY created_at, id"
      )
      result = []
      for row in await cursor.fetchall():
        run = await self.read_run(row["id"], row["thread_id"])
        assert run is not None
        result.append(run)
      return result

  async def get_run(self, run_id: str, thread_id: str) -> RunSnapshot | None:
    # 同一连接的读也必须等写事务结束，不能把尚未提交的状态暴露出去。
    async with self._db.lock:
      return await self.read_run(run_id, thread_id)

  async def read_run(self, run_id: str, thread_id: str) -> RunSnapshot | None:
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
    usage, pending = await self.read_usage(run_id, thread_id)
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

  async def read_usage(
    self, run_id: str, thread_id: str
  ) -> tuple[UsageData | None, bool]:
    """调用方持有数据库锁；没有结算记录时返回未知，而非零消耗。"""
    cursor = await self._db.connection.execute(
      "SELECT usage_json FROM run_usage WHERE run_id = ? AND thread_id = ?",
      (run_id, thread_id),
    )
    rows = list(await cursor.fetchall())
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
