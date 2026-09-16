"""离线产品库迁移：只修改独占创建的副本，不改写来源或切换运行配置。"""

import argparse
import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.persistence.event_store import EventStore
from app.persistence.schema import SCHEMA

COLUMNS = {
  "threads": "id user_id title created_at updated_at".split(),
  "runs": "id thread_id status error created_at updated_at completed_at".split(),
  "run_events": (
    "id thread_id run_id seq event_type category event_key "
    "content_json metadata_json created_at"
  ).split(),
}
TERMINAL = {"completed", "error", "cancelled"}
STATUSES = TERMINAL | {"pending", "running", "interrupted"}


def _normalize_sql(value: str) -> str:
  return "".join(value.lower().split()).replace("ifnotexists", "")


def _rows(connection: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
  return [dict(row) for row in connection.execute(f'SELECT * FROM "{table}"')]


def _audit(connection: sqlite3.Connection) -> tuple[dict, dict]:
  """返回可序列化报告和转换计划；不修改被审计的数据。"""
  report: dict[str, Any] = {
    "source_version": None,
    "target_version": 1,
    "issues": [],
    "changes": [],
    "counts": {},
  }

  def issue(code: str, **details: Any) -> None:
    report["issues"].append({"code": code, **details})

  tables = {
    row[0]
    for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
  }
  version = 0
  if "chat_schema" in tables:
    try:
      versions = [
        row[0] for row in connection.execute("SELECT version FROM chat_schema")
      ]
    except sqlite3.DatabaseError:
      versions = []
    if versions != [1]:
      issue("unsupported_version", versions=versions)
    version = 1
  report["source_version"] = version
  for table, columns in COLUMNS.items():
    actual = {row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')}
    expected = set(columns)
    if table == "runs" and version == 1:
      expected.add("error_code")
    if table == "run_events" and version == 0:
      actual.add("event_key")  # 最早版本允许缺少此列。
    if actual != expected:
      issue("unsupported_columns", table=table, columns=sorted(actual))
  # 重建产品表会丢失自定义触发器/索引；未知扩展必须显式处理。
  known_indexes = {
    "ix_runs_thread_created",
    "ix_run_events_run_category_seq",
    "uq_run_events_event_key",
    "uq_runs_one_nonterminal_per_thread",
  }
  for row in connection.execute(
    "SELECT type, name, tbl_name, sql FROM sqlite_master WHERE sql IS NOT NULL"
  ):
    if row["tbl_name"] in COLUMNS and (
      row["type"] == "trigger"
      or (row["type"] == "index" and row["name"] not in known_indexes)
    ):
      issue("unsupported_schema_object", name=row["name"])
  if version == 1:
    # 版本号不能替代表结构检查，拒绝仅手工加了版本标记的旧库。
    with closing(sqlite3.connect(":memory:")) as expected_schema:
      expected_schema.executescript(SCHEMA)
      expected_schema.execute(
        "CREATE UNIQUE INDEX uq_run_events_event_key "
        "ON run_events(thread_id, run_id, event_key) WHERE event_key IS NOT NULL"
      )
      for name, sql in expected_schema.execute(
        "SELECT name, sql FROM sqlite_master WHERE sql IS NOT NULL"
      ):
        actual_sql = connection.execute(
          "SELECT sql FROM sqlite_master WHERE name=?", (name,)
        ).fetchone()
        if actual_sql is None or _normalize_sql(actual_sql[0]) != _normalize_sql(sql):
          issue("schema_definition_mismatch", name=name)
  for table in tables - set(COLUMNS) - {"sqlite_sequence", "chat_schema"}:
    for fk in connection.execute(
      'PRAGMA foreign_key_list("' + table.replace('"', '""') + '")'
    ):
      if fk[2] in COLUMNS:
        issue("external_product_reference", table=table)
  if report["issues"]:
    return report, {}
  for row in connection.execute("PRAGMA integrity_check"):
    if row[0] != "ok":
      issue("integrity_check", detail=row[0])
  for row in connection.execute("PRAGMA foreign_key_check"):
    issue("foreign_key_check", table=row[0], rowid=row[1])

  for table in COLUMNS:
    for row in connection.execute(
      f"SELECT id, COUNT(*) FROM {table} GROUP BY id HAVING COUNT(*) > 1"
    ):
      issue("duplicate_id", table=table, id=row[0])
  data = {table: _rows(connection, table) for table in COLUMNS}
  report["counts"] = {table: len(rows) for table, rows in data.items()}
  threads = {row["id"] for row in data["threads"]}
  runs = {(row["thread_id"], row["id"]): row for row in data["runs"]}
  active: dict[str, list[str]] = {}
  for table, rows in data.items():
    for row in rows:
      for field in ("id", "created_at"):
        if row[field] is None:
          issue("missing_required_value", table=table, field=field)
      if table != "run_events" and row["updated_at"] is None:
        issue("missing_required_value", table=table, field="updated_at", id=row["id"])
  for row in data["runs"]:
    if row["thread_id"] not in threads:
      issue("orphan_run", run_id=row["id"])
    if row["status"] not in STATUSES:
      issue("invalid_status", run_id=row["id"], status=row["status"])
    elif (row["status"] in TERMINAL) != (row["completed_at"] is not None):
      issue("inconsistent_completion_time", run_id=row["id"])
    if row["status"] not in TERMINAL:
      active.setdefault(row["thread_id"], []).append(row["id"])
    if version == 0:
      row["error_code"] = "legacy_error" if row["status"] == "error" else None
      if row["error_code"]:
        report["changes"].append({"kind": "legacy_error_code", "run_id": row["id"]})
  for thread, ids in active.items():
    if len(ids) > 1:
      issue("multiple_nonterminal_runs", thread_id=thread, run_ids=ids)
    else:
      report["changes"].append({"kind": "preserve_nonterminal", "run_id": ids[0]})

  identities: dict[tuple, dict] = {}
  sequences: set[tuple] = set()
  messages: dict[tuple, dict] = {}
  for row in data["run_events"]:
    row.setdefault("event_key", None)
    ref = {"event_id": row["id"], "run_id": row["run_id"]}
    if (row["thread_id"], row["run_id"]) not in runs:
      issue("orphan_event", **ref)
    seq = (row["thread_id"], row["seq"])
    if not isinstance(row["seq"], int) or row["seq"] < 1 or seq in sequences:
      issue("invalid_or_duplicate_seq", **ref)
    sequences.add(seq)
    try:
      content = json.loads(row["content_json"])
      metadata = json.loads(row["metadata_json"])
      EventStore._json(content)
      EventStore._json(metadata)
      if not isinstance(metadata, dict):
        raise ValueError("metadata must be an object")
      if row["category"] == "message" or row["event_type"].endswith("_message"):
        kind, key = EventStore.message_identity(content)
        if row["event_type"] != kind or row["category"] != "message":
          raise ValueError("message type/category mismatch")
        if row["event_key"] is None and version == 0:
          row["event_key"] = key
          report["changes"].append({"kind": "derive_message_key", **ref, "key": key})
        elif row["event_key"] != key:
          raise ValueError("message identity/key mismatch")
        identity = (row["thread_id"], key)
        if identity in messages:
          previous = messages[identity]
          issue("repeated_message_identity", **ref, previous_event_id=previous["id"])
        messages[identity] = row
      if row["category"] == "lifecycle" or row["event_type"].startswith("run_"):
        if (
          row["category"] != "lifecycle"
          or not isinstance(content, dict)
          or content.get("status") not in STATUSES
          or row["event_type"] != f"run_{content['status']}"
        ):
          raise ValueError("invalid lifecycle fact")
    except (TypeError, ValueError, AttributeError) as error:
      issue("invalid_event", **ref, detail=str(error))
    if row["event_key"] is not None:
      identity = (row["thread_id"], row["run_id"], row["event_key"])
      if identity in identities:
        issue(
          "duplicate_event_key", **ref, previous_event_id=identities[identity]["id"]
        )
      identities[identity] = row

  for identity, run in runs.items():
    if run["status"] == "pending" or run["status"] not in STATUSES:
      continue
    key = (
      f"running:{run['id']}" if run["status"] == "running" else f"settled:{run['id']}"
    )
    existing = identities.get((*identity, key))
    if existing:
      try:
        content = json.loads(existing["content_json"])
        if (
          existing["category"] != "lifecycle"
          or existing["event_type"] != f"run_{run['status']}"
          or content.get("status") != run["status"]
        ):
          issue("settlement_mismatch", run_id=run["id"])
      except (ValueError, AttributeError):
        issue("settlement_mismatch", run_id=run["id"])
    elif version == 0:
      report["changes"].append(
        {"kind": "status_snapshot", "run_id": run["id"], "key": key}
      )
    else:
      issue("missing_lifecycle_fact", run_id=run["id"])
  return report, data


def _upgrade(connection: sqlite3.Connection, data: dict, report: dict) -> None:
  """一个事务内重建产品表，保留 checkpoint 表与 SQLite user_version。"""
  high_water = (
    connection.execute(
      "SELECT seq FROM sqlite_sequence WHERE name='run_events'"
    ).fetchone()
    if connection.execute(
      "SELECT 1 FROM sqlite_master WHERE name='sqlite_sequence'"
    ).fetchone()
    else None
  )
  connection.execute("PRAGMA foreign_keys=OFF")
  connection.execute("BEGIN IMMEDIATE")
  try:
    for table in ("run_events", "runs", "threads"):
      connection.execute(f"DROP TABLE {table}")
    for statement in SCHEMA.split(";"):
      if statement.strip():
        connection.execute(statement)
    connection.execute(
      "CREATE UNIQUE INDEX uq_run_events_event_key "
      "ON run_events(thread_id, run_id, event_key) WHERE event_key IS NOT NULL"
    )
    for table, rows in data.items():
      columns = COLUMNS[table] + (["error_code"] if table == "runs" else [])
      connection.executemany(
        f"INSERT INTO {table} ({','.join(columns)}) "
        f"VALUES ({','.join('?' for _ in columns)})",
        [tuple(row[col] for col in columns) for row in rows],
      )
    if high_water:
      connection.execute("DELETE FROM sqlite_sequence WHERE name='run_events'")
      connection.execute(
        "INSERT INTO sqlite_sequence(name,seq) VALUES ('run_events', ?)",
        (high_water[0],),
      )
    now = datetime.now(UTC).isoformat()
    runs = {row["id"]: row for row in data["runs"]}
    for change in report["changes"]:
      if change["kind"] != "status_snapshot":
        continue
      run = runs[change["run_id"]]
      content = {"status": run["status"]}
      if run["error"] is not None:
        content["message"] = run["error"]
      if run["error_code"] is not None:
        content["error_code"] = run["error_code"]
      metadata = {
        "migration": {
          "source_version": 0,
          "kind": "status_snapshot",
          "observed_at": now,
          "historical_transition_time_known": False,
          "source_updated_at": run["updated_at"],
          "source_completed_at": run["completed_at"],
        }
      }
      connection.execute(
        "INSERT INTO run_events(thread_id,run_id,seq,event_type,category,event_key,"
        "content_json,metadata_json,created_at) "
        "SELECT ?,?,COALESCE(MAX(seq),0)+1,?,'lifecycle',?,?,?,? "
        "FROM run_events WHERE thread_id=?",
        (
          run["thread_id"],
          run["id"],
          f"run_{run['status']}",
          change["key"],
          EventStore._json(content),
          EventStore._json(metadata),
          now,
          run["thread_id"],
        ),
      )
    if connection.execute("PRAGMA foreign_key_check").fetchone():
      raise ValueError("Foreign key validation failed after migration")
    connection.commit()
  except BaseException:
    connection.rollback()
    raise
  finally:
    connection.execute("PRAGMA foreign_keys=ON")


def prepare_copy(source: Path, destination: Path, *, upgrade: bool = False) -> dict:
  """backup 后审计；upgrade 仅升级新副本。失败保留可读取的旧格式副本。"""
  source = source.resolve(strict=True)
  destination = destination.absolute()
  # 独占创建，拒绝来源路径、已有文件和符号链接，绝不覆盖备份。
  with destination.open("xb"):
    pass
  with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as src:
    with closing(sqlite3.connect(destination)) as dst:
      dst.row_factory = sqlite3.Row
      src.backup(dst)
      report, data = _audit(dst)
      report.update(source=str(source), destination=str(destination), upgraded=False)
      if upgrade and not report["issues"] and report["source_version"] == 0:
        _upgrade(dst, data, report)
        report["upgraded"] = True
      return report


def main() -> int:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("source", type=Path)
  parser.add_argument("destination", type=Path, help="必须是尚不存在的副本路径")
  parser.add_argument("--upgrade", action="store_true", help="审计通过后升级副本")
  args = parser.parse_args()
  try:
    report = prepare_copy(args.source, args.destination, upgrade=args.upgrade)
  except (OSError, sqlite3.Error, ValueError) as error:
    print(json.dumps({"error": str(error)}, ensure_ascii=False))
    return 1
  print(json.dumps(report, ensure_ascii=False, indent=2))
  return 2 if report["issues"] else 0


if __name__ == "__main__":
  raise SystemExit(main())
