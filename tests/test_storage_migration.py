"""4B 离线副本迁移：旧数据保留、冲突报告和失败回滚。"""

import asyncio
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from langchain_core.messages import HumanMessage
from shikigen.execution import ExecutionOutcome, ExecutionReason

from app.persistence import ChatStore
from app.persistence.event_store import EventStore
from app.persistence.migrate import prepare_copy

# 固定旧格式 fixture；不从新 schema 反向生成旧库。
LEGACY_SCHEMA = """
CREATE TABLE threads(id TEXT PRIMARY KEY, user_id TEXT, title TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE runs(id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, status TEXT NOT NULL,
  error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, completed_at TEXT,
  FOREIGN KEY(thread_id) REFERENCES threads(id), UNIQUE(thread_id,id));
CREATE TABLE run_events(id INTEGER PRIMARY KEY AUTOINCREMENT,
  thread_id TEXT NOT NULL, run_id TEXT NOT NULL, seq INTEGER NOT NULL,
  event_type TEXT NOT NULL, category TEXT NOT NULL, event_key TEXT,
  content_json TEXT NOT NULL, metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL, UNIQUE(thread_id,seq),
  FOREIGN KEY(thread_id,run_id) REFERENCES runs(thread_id,id));
CREATE TABLE checkpoints(thread_id TEXT, checkpoint BLOB);
CREATE TABLE writes(thread_id TEXT, value BLOB);
PRAGMA user_version=7;
INSERT INTO checkpoints VALUES('thread',X'0001FF');
INSERT INTO writes VALUES('thread',X'FE02');
INSERT INTO threads VALUES('thread','user','title','created','updated');
INSERT INTO runs VALUES('run','thread','completed',NULL,'created','updated','done');
"""


class MigrationTests(unittest.IsolatedAsyncioTestCase):
  def setUp(self):
    directory = tempfile.TemporaryDirectory()
    self.addCleanup(directory.cleanup)
    self.source = Path(directory.name) / "old.db"
    self.target = Path(directory.name) / "new.db"
    with sqlite3.connect(self.source) as connection:
      connection.executescript(LEGACY_SCHEMA)
      connection.execute(
        "INSERT INTO run_events VALUES(7,'thread','run',3,'human_message',"
        "'message',NULL,?,'{}','message-time')",
        (json.dumps({"type": "human", "message_id": "human", "content": "hello"}),),
      )
      # 删除过的高水位也保留，迁移合成事件不可复用旧事件 ID。
      connection.execute("UPDATE sqlite_sequence SET seq=20 WHERE name='run_events'")

  def execute(self, sql, parameters=()):
    with sqlite3.connect(self.source) as connection:
      connection.execute(sql, parameters)

  async def test_upgrade_preserves_history_checkpoint_and_runtime_operations(self):
    before = self.source.read_bytes()
    report = prepare_copy(self.source, self.target, upgrade=True)
    self.assertTrue(report["upgraded"])
    self.assertEqual(report["issues"], [])
    self.assertEqual(self.source.read_bytes(), before)
    with sqlite3.connect(self.target) as connection:
      self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 7)
      self.assertEqual(
        connection.execute("SELECT checkpoint FROM checkpoints").fetchone()[0],
        b"\x00\x01\xff",
      )
      self.assertEqual(
        connection.execute("SELECT value FROM writes").fetchone()[0], b"\xfe\x02"
      )
      self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
      with self.assertRaises(sqlite3.IntegrityError):
        connection.execute("UPDATE runs SET status='invalid'")
    store = await ChatStore.open(self.target)
    try:
      thread = (await store.list_threads())[0]
      self.assertEqual((thread["user_id"], thread["title"]), ("user", "title"))
      events = await store.list_run_events("thread", "run")
      self.assertEqual(
        (events[0]["id"], events[0]["seq"], events[0]["created_at"]),
        (7, 3, "message-time"),
      )
      self.assertEqual(events[0]["event_key"], "human:human")
      self.assertEqual((events[1]["id"], events[1]["seq"]), (21, 4))
      self.assertEqual(events[1]["metadata"]["migration"]["kind"], "status_snapshot")
      self.assertFalse(
        events[1]["metadata"]["migration"]["historical_transition_time_known"]
      )
      self.assertNotEqual(events[1]["created_at"], "done")
      settled = await store.settle_execution(
        thread_id="thread",
        run_id="run",
        outcome=ExecutionOutcome(ExecutionReason.COMPLETED),
      )
      self.assertFalse(settled.changed)
      self.assertEqual(settled.events[0], events[1])
      replay = await store.append_message(
        thread_id="thread", run_id="run", content=events[0]["content"]
      )
      self.assertFalse(replay.inserted)
      created = await store.create_run(
        thread_id="thread",
        run_id="next",
        entry_message=HumanMessage(id="next-human", content="next"),
      )
      self.assertEqual(created.events[0]["seq"], 5)
    finally:
      await store.close()

  async def test_audit_only_and_repeat_version_one(self):
    report = prepare_copy(self.source, self.target)
    self.assertFalse(report["upgraded"])
    with sqlite3.connect(self.target) as connection:
      self.assertEqual(
        connection.execute(
          "SELECT name FROM sqlite_master WHERE name='chat_schema'"
        ).fetchall(),
        [],
      )
    upgraded = self.target.with_name("upgraded.db")
    prepare_copy(self.target, upgraded, upgrade=True)
    again = self.target.with_name("again.db")
    report = prepare_copy(upgraded, again, upgrade=True)
    self.assertEqual(report["source_version"], 1)
    self.assertFalse(report["upgraded"])
    self.assertEqual(report["issues"], [])
    with sqlite3.connect(again) as connection:
      self.assertEqual(
        connection.execute("SELECT COUNT(*) FROM run_events").fetchone()[0], 2
      )

  async def test_oldest_schema_without_event_key(self):
    self.execute("ALTER TABLE run_events DROP COLUMN event_key")
    report = prepare_copy(self.source, self.target, upgrade=True)
    self.assertTrue(report["upgraded"])

  async def test_conflicts_report_all_and_keep_old_copy_readable(self):
    self.execute("UPDATE runs SET status='running',completed_at=NULL")
    self.execute(
      "INSERT INTO runs VALUES('other','thread','interrupted',NULL,'c','u',NULL)"
    )
    self.execute(
      "INSERT INTO run_events SELECT 8,thread_id,'other',4,event_type,category,"
      "NULL,content_json,metadata_json,created_at FROM run_events"
    )
    self.execute("INSERT INTO runs VALUES('bad','missing','error',NULL,'c','u',NULL)")
    before = self.source.read_bytes()
    report = prepare_copy(self.source, self.target, upgrade=True)
    codes = {issue["code"] for issue in report["issues"]}
    self.assertTrue(
      {
        "multiple_nonterminal_runs",
        "repeated_message_identity",
        "orphan_run",
        "inconsistent_completion_time",
      }
      <= codes
    )
    self.assertFalse(report["upgraded"])
    self.assertEqual(self.source.read_bytes(), before)
    with sqlite3.connect(self.target) as connection:
      self.assertEqual(connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0], 3)
      self.assertNotIn(
        "error_code", [row[1] for row in connection.execute("PRAGMA table_info(runs)")]
      )

  async def test_unknown_version_schema_and_invalid_payload_are_rejected(self):
    cases = [
      ("CREATE TABLE chat_schema(version INTEGER)", "unsupported_version"),
      ("ALTER TABLE runs ADD COLUMN custom TEXT", "unsupported_columns"),
      ("UPDATE run_events SET content_json='{}'", "invalid_event"),
      ("UPDATE run_events SET metadata_json='[]'", "invalid_event"),
      ("CREATE INDEX custom_index ON runs(status)", "unsupported_schema_object"),
    ]
    for index, (sql, code) in enumerate(cases):
      with self.subTest(code=code):
        source = self.target.with_name(f"case-{index}.db")
        prepare_copy(self.source, source)
        with sqlite3.connect(source) as connection:
          connection.execute(sql)
        report = prepare_copy(
          source, self.target.with_name(f"result-{index}.db"), upgrade=True
        )
        self.assertIn(code, {item["code"] for item in report["issues"]})
        self.assertFalse(report["upgraded"])

  async def test_transaction_failure_rolls_back_ddl_and_data(self):
    with patch("app.persistence.migrate.SCHEMA", "CREATE TABLE broken(;"):
      with self.assertRaises(sqlite3.OperationalError):
        prepare_copy(self.source, self.target, upgrade=True)
    with sqlite3.connect(self.target) as connection:
      self.assertEqual(
        connection.execute("SELECT title FROM threads").fetchone()[0], "title"
      )
      self.assertEqual(
        connection.execute("SELECT id FROM run_events").fetchall(), [(7,)]
      )
      self.assertNotIn(
        "error_code", [row[1] for row in connection.execute("PRAGMA table_info(runs)")]
      )
    retry = self.target.with_name("retry.db")
    self.assertTrue(prepare_copy(self.target, retry, upgrade=True)["upgraded"])

  async def test_existing_target_and_source_are_never_overwritten(self):
    before = self.source.read_bytes()
    with self.assertRaises(FileExistsError):
      prepare_copy(self.source, self.source, upgrade=True)
    self.target.symlink_to(self.source)
    with self.assertRaises(FileExistsError):
      prepare_copy(self.source, self.target, upgrade=True)
    self.assertEqual(self.source.read_bytes(), before)

  async def test_backup_includes_committed_wal_data(self):
    with sqlite3.connect(self.source) as writer:
      writer.execute("PRAGMA journal_mode=WAL")
      writer.execute("UPDATE threads SET title='wal-title'")
      writer.commit()
      report = prepare_copy(self.source, self.target, upgrade=True)
      self.assertTrue(report["upgraded"])
      with sqlite3.connect(self.target) as reader:
        self.assertEqual(
          reader.execute("SELECT title FROM threads").fetchone()[0], "wal-title"
        )

  async def test_existing_settlement_is_not_replaced(self):
    payload = json.dumps({"status": "completed"})
    self.execute(
      "INSERT INTO run_events VALUES(8,'thread','run',4,'run_completed',"
      "'lifecycle','settled:run',?,'{}','done')",
      (payload,),
    )
    report = prepare_copy(self.source, self.target, upgrade=True)
    self.assertFalse(any(c["kind"] == "status_snapshot" for c in report["changes"]))
    with sqlite3.connect(self.target) as connection:
      self.assertEqual(
        connection.execute(
          "SELECT content_json,created_at FROM run_events WHERE id=8"
        ).fetchone(),
        (payload, "done"),
      )

  async def test_cli_rejection_exit_code_and_json_report(self):
    self.execute("UPDATE run_events SET content_json='{}'")
    result = subprocess.run(
      [
        sys.executable,
        "-m",
        "app.persistence.migrate",
        str(self.source),
        str(self.target),
        "--upgrade",
      ],
      capture_output=True,
      text=True,
      timeout=15,
    )
    self.assertEqual(result.returncode, 2, result.stderr)
    self.assertFalse(json.loads(result.stdout)["upgraded"])

  async def test_cancellation_after_rebuild_rolls_back(self):
    original = EventStore._json

    def fail_snapshot(value):
      if isinstance(value, dict) and value.get("status") == "completed":
        raise asyncio.CancelledError()
      return original(value)

    with patch.object(EventStore, "_json", side_effect=fail_snapshot):
      with self.assertRaises(asyncio.CancelledError):
        prepare_copy(self.source, self.target, upgrade=True)
    with sqlite3.connect(self.target) as connection:
      self.assertEqual(
        connection.execute("SELECT id FROM run_events").fetchall(), [(7,)]
      )
      self.assertEqual(
        connection.execute(
          "SELECT name FROM sqlite_master WHERE name='chat_schema'"
        ).fetchall(),
        [],
      )

  async def test_legacy_error_and_nonterminal_states_keep_their_meaning(self):
    for status in ("error", "cancelled", "pending", "running", "interrupted"):
      with self.subTest(status=status):
        self.execute(
          "UPDATE runs SET status=?, completed_at=?, error=?",
          (
            status,
            "done" if status in ("error", "cancelled") else None,
            "legacy failure" if status == "error" else None,
          ),
        )
        target = self.target.with_name(f"{status}.db")
        report = prepare_copy(self.source, target, upgrade=True)
        self.assertTrue(report["upgraded"])
        store = await ChatStore.open(target)
        try:
          run = await store.get_run("run", "thread")
          self.assertEqual(run["status"], status)
          self.assertEqual(
            run["error_code"], "legacy_error" if status == "error" else None
          )
          if status in ("error", "cancelled", "interrupted"):
            result = await store.settle_execution(
              thread_id="thread",
              run_id="run",
              outcome=ExecutionOutcome(ExecutionReason.COMPLETED),
            )
            self.assertEqual(result.status, status)
            self.assertFalse(result.changed)
        finally:
          await store.close()

  async def test_version_marker_cannot_hide_missing_constraints(self):
    self.execute("CREATE TABLE chat_schema(version INTEGER PRIMARY KEY)")
    self.execute("INSERT INTO chat_schema VALUES(1)")
    self.execute("ALTER TABLE runs ADD COLUMN error_code TEXT")
    report = prepare_copy(self.source, self.target, upgrade=True)
    self.assertIn("schema_definition_mismatch", {i["code"] for i in report["issues"]})
    self.assertFalse(report["upgraded"])
