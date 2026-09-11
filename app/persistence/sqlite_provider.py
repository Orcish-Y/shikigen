from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver


@asynccontextmanager
async def make_sqlite_checkpointer(
  database_path: str | Path,
) -> AsyncIterator[AsyncSqliteSaver]:
  """Create a SQLite checkpointer for the caller's application lifetime."""
  path = Path(database_path)
  path.parent.mkdir(parents=True, exist_ok=True)

  async with AsyncSqliteSaver.from_conn_string(str(path)) as checkpointer:
    await checkpointer.setup()
    yield checkpointer
