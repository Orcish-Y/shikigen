"""真实子进程里的 runtime；只替换模型，不替换数据库、文件系统或原生锁。"""

import asyncio
import json
import subprocess
import sys
from unittest.mock import patch

from runtime_fixtures import deterministic_agent
from shikigen.app_config import AppConfig
from shikigen.runtime import open_runtime


def report(**data):
  print(json.dumps(data), flush=True)


async def main():
  config = AppConfig.model_validate_json(sys.argv[1])
  try:
    with patch(
      "shikigen.runtime.composition.create_lead_agent", new=deterministic_agent
    ):
      async with open_runtime(config) as runtime:
        report(status="ready")
        while command := (await asyncio.to_thread(sys.stdin.readline)).strip():
          if command == "exit":
            break
          if command == "spawn":
            child = subprocess.Popen(
              [sys.executable, "-c", "import time; time.sleep(120)"],
              close_fds=False,
              stdin=subprocess.DEVNULL,
              stdout=subprocess.DEVNULL,
              stderr=subprocess.DEVNULL,
            )
            report(status="spawned", pid=child.pid)
          elif command == "run":
            threads = await asyncio.gather(
              runtime.threads.create_thread(), runtime.threads.create_thread()
            )
            runs = await asyncio.gather(
              *(runtime.runs.start_run(thread, "1 + 2") for thread in threads)
            )
            rows = await asyncio.gather(*(runtime.runs.wait_run(run) for run in runs))
            report(status="ran", results=[row["status"] for row in rows])
      # Both real SQLite connections must be closed before a successor can enter.
      try:
        await runtime.chat_store.list_threads(limit=20)
      except ValueError:
        pass
      else:
        raise AssertionError("chat connection remains open")
      if config.checkpointer.type == "sqlite":
        try:
          await runtime.checkpointer.conn.execute("SELECT 1")
        except ValueError:
          pass
        else:
          raise AssertionError("checkpoint connection remains open")
      report(status="closed")
  except Exception as error:
    report(status="failed", error=type(error).__name__, message=str(error))
    sys.exit(2)


if __name__ == "__main__":
  asyncio.run(main())
