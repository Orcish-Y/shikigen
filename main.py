import asyncio
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv
from langchain.messages import HumanMessage

from harness import StreamManager, create_lead_agent, run_agent_loop
from harness.checkpoint.sqlite_provider import make_sqlite_checkpointer
from harness.run_manager import RunManager, RunRecord, RunStatus
from harness.stream import MessageData, ToolCallData
from text_safety import replace_surrogates

load_dotenv()

output_path = Path("output.json")
checkpoint_db_path = Path(".shikigen/data/shikigen.db")


def consume_messages(message: MessageData) -> None:
  print(message["text"], end="", flush=True)


def consume_tool_calls(call: ToolCallData) -> None:
  print(f"\nTool call: {call['name']}({call['input']})")
  print(f"\nTool result: {call['output']}")


stream_manager = StreamManager()
run_manager = RunManager(stream_manager)


async def consume_agent_events(
  record: RunRecord,
  agent_task: asyncio.Task[None],
  manager: RunManager,
) -> None:
  terminal_status: RunStatus | None = None

  async for event in record.stream.subscribe():
    if event.event == "message":
      consume_messages(event.data)
    elif event.event == "tool_call":
      consume_tool_calls(event.data)
    elif event.event == "status":
      terminal_status = RunStatus(event.data["status"])

  await agent_task

  if terminal_status is None:
    raise RuntimeError("Agent completed without a terminal status")

  manager.set_status(record.run_id, terminal_status)


async def run_interactive_loop(agent) -> None:
  print("你好主人，有什么可以帮助你的？\n")
  thread_id = "default"

  while True:
    try:
      user_input = input(">")

    except (EOFError, KeyboardInterrupt):
      print("\n再见喵~")
      break

    if user_input.strip().lower() in ("/exit", "/quit", "/q"):
      print("再见喵~")
      break

    # Keep the API boundary safe even when text originates outside stdin.
    record = run_manager.create(thread_id=thread_id)

    agent_task = asyncio.create_task(
      run_agent_loop(
        agent,
        new_message=HumanMessage(content=replace_surrogates(user_input)),
        record=record,
      )
    )

    record.task = agent_task
    record.status = RunStatus.RUNNING

    try:
      await consume_agent_events(record, agent_task, run_manager)

    except Exception as error:
      run_manager.set_status(record.run_id, RunStatus.ERROR)
      print(f"\nError: {error}")

    finally:
      run_manager.remove(record.run_id)


async def main():
  logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
  )
  # Avoid creating surrogate characters if a terminal sends malformed UTF-8.
  sys.stdin.reconfigure(encoding="utf-8", errors="replace")

  async with make_sqlite_checkpointer(checkpoint_db_path) as checkpointer:
    agent = create_lead_agent(
      model="deepseek:deepseek-v4-flash",
      checkpointer=checkpointer,
    )
    await run_interactive_loop(agent)


if __name__ == "__main__":
  asyncio.run(main())
