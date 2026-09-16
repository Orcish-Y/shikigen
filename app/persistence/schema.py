"""产品数据库的表结构、版本检查与初始化。"""

import aiosqlite

from app.run_state import SchemaMigrationRequired

SCHEMA = """
CREATE TABLE IF NOT EXISTS threads (
  id TEXT PRIMARY KEY,
  user_id TEXT,
  title TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY,
  thread_id TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN (
    'pending', 'running', 'interrupted', 'completed', 'error', 'cancelled'
  )),
  error TEXT,
  error_code TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  completed_at TEXT,
  CHECK ((status IN ('completed', 'error', 'cancelled'))
    = (completed_at IS NOT NULL)),
  FOREIGN KEY (thread_id) REFERENCES threads(id) ON DELETE CASCADE,
  UNIQUE (thread_id, id)
);

CREATE INDEX IF NOT EXISTS ix_runs_thread_created
  ON runs(thread_id, created_at);

CREATE UNIQUE INDEX IF NOT EXISTS uq_runs_one_nonterminal_per_thread
  ON runs(thread_id) WHERE status NOT IN ('completed', 'error', 'cancelled');

CREATE TABLE IF NOT EXISTS chat_schema (version INTEGER PRIMARY KEY);
INSERT OR IGNORE INTO chat_schema(version) VALUES (1);

CREATE TABLE IF NOT EXISTS run_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  thread_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  seq INTEGER NOT NULL,
  event_type TEXT NOT NULL,
  category TEXT NOT NULL,
  event_key TEXT,
  content_json TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  FOREIGN KEY (thread_id, run_id) REFERENCES runs(thread_id, id)
    ON DELETE CASCADE,
  UNIQUE (thread_id, seq)
);

CREATE INDEX IF NOT EXISTS ix_run_events_run_category_seq
  ON run_events(thread_id, run_id, category, seq);

"""


async def setup_schema(connection: aiosqlite.Connection) -> None:
  cursor = await connection.execute(
    "SELECT name FROM sqlite_master WHERE type = 'table' AND name IN "
    "('threads', 'runs', 'run_events', 'chat_schema')"
  )
  tables = {row[0] for row in await cursor.fetchall()}
  if tables:
    if tables != {"threads", "runs", "run_events", "chat_schema"}:
      raise SchemaMigrationRequired("Product database requires a 4B migration")
    cursor = await connection.execute("SELECT version FROM chat_schema")
    if [row[0] for row in await cursor.fetchall()] != [1]:
      raise SchemaMigrationRequired("Unsupported product schema version")
  # 不改写旧产品库；新库建表与约束在同一事务中安装。
  try:
    await connection.executescript(
      "BEGIN IMMEDIATE;\n"
      + SCHEMA
      + """
      CREATE UNIQUE INDEX IF NOT EXISTS uq_run_events_event_key
      ON run_events(thread_id, run_id, event_key)
      WHERE event_key IS NOT NULL;
      COMMIT;
      """
    )
  except BaseException:
    await connection.rollback()
    raise
