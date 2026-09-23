"""产品数据库的当前表结构与初始化。旧数据库不做迁移。"""

import aiosqlite

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
    'running', 'interrupted', 'completed', 'error', 'cancelled'
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

-- todo. 这个需要存储吗？？
CREATE TABLE IF NOT EXISTS run_usage (
  thread_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  invocation_seq INTEGER NOT NULL,
  usage_json TEXT NOT NULL,
  PRIMARY KEY (thread_id, run_id, invocation_seq),
  FOREIGN KEY (thread_id, run_id) REFERENCES runs(thread_id, id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS thread_sequences (
  thread_id TEXT PRIMARY KEY REFERENCES threads(id) ON DELETE CASCADE,
  value INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS message_sequences (
  thread_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  event_key TEXT NOT NULL,
  seq INTEGER NOT NULL,
  PRIMARY KEY (thread_id, event_key),
  UNIQUE (thread_id, seq),
  FOREIGN KEY (thread_id, run_id) REFERENCES runs(thread_id, id) ON DELETE CASCADE
);

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

CREATE UNIQUE INDEX IF NOT EXISTS uq_thread_message_identity
  ON run_events(thread_id, event_key) WHERE category = 'message';

CREATE INDEX IF NOT EXISTS ix_run_events_run_category_seq
  ON run_events(thread_id, run_id, category, seq);

"""


async def setup_schema(connection: aiosqlite.Connection) -> None:
  # 只安装当前 schema；历史数据库由部署者删除，不在启动时转换或检查。
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
