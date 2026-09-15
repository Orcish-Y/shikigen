"""最小无 HTTP 入口：python -m app.run --config config.json '你好'。"""

import argparse
import asyncio
import json

from shikigen.app_config import load_app_config

from app.composition import open_runtime


async def main() -> None:
  parser = argparse.ArgumentParser(description="执行并持久化一次 Agent Run")
  parser.add_argument("message")
  parser.add_argument("--config", default="config.json")
  parser.add_argument("--thread-id", help="沿用已有 Thread；缺省时创建")
  args = parser.parse_args()
  async with open_runtime(load_app_config(args.config)) as runtime:
    thread_id = args.thread_id or await runtime.threads.create_thread()
    execution = await runtime.runs.start_run(thread_id, args.message)
    print(json.dumps({"thread_id": thread_id, "run_id": execution.run_id}), flush=True)
    row = await runtime.runs.wait_run(execution)
    print(json.dumps(row, ensure_ascii=False))
    print(
      json.dumps(
        await runtime.runs.list_run_messages(thread_id, execution.run_id),
        ensure_ascii=False,
      )
    )
    if row["status"] in ("error", "cancelled"):
      raise SystemExit(1)


if __name__ == "__main__":
  asyncio.run(main())
