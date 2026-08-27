import asyncio
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv
from langchain.messages import HumanMessage

from harness import StreamManager, create_lead_agent, run_agent_loop
from harness.app_config import load_app_config
from harness.callback_handler import TokenTracker
from harness.checkpoint.sqlite_provider import make_sqlite_checkpointer
from harness.model import create_chat_model
from harness.run_manager import RunManager, RunRecord, RunStatus
from harness.stream import MessageData, ToolCallData, UsageData
from text_safety import replace_surrogates
from tools import create_builtin_registry
from tools.mcp_loader import load_mcp_tools

load_dotenv()

output_path = Path("output.json")
checkpoint_db_path = Path(".shikigen/data/shikigen.db")


def consume_messages(message: MessageData) -> None:
  if not message["done"]:
    print(message["text"], end="", flush=True)


def consume_tool_calls(call: ToolCallData) -> None:
  print(f"\nTool call: {call['name']}({call['input']})")
  print(f"\nTool result: {call['output']}")


stream_manager = StreamManager()
run_manager = RunManager(stream_manager)


def consume_usage(data: UsageData) -> None:
  """打印 token 用量统计。"""
  print(
    f"\n[Usage] {data['total_input']} in + {data['total_output']} out "
    f"= {data['total_tokens']} tokens ({data['calls']} LLM call(s))"
  )
  for model, stats in data.get("by_model", {}).items():
    print(f"  {model}: {stats['input']} in / {stats['output']} out")


async def consume_agent_events(
  record: RunRecord,
  agent_task: asyncio.Task[None],
) -> None:
  async for event in record.stream.subscribe():
    if event.event == "message":
      consume_messages(event.data)
    elif event.event == "tool_call":
      consume_tool_calls(event.data)
    elif event.event == "usage":
      consume_usage(event.data)

  await agent_task

  if record.status not in (
    RunStatus.COMPLETED,
    RunStatus.CANCELLED,
    RunStatus.ERROR,
  ):
    raise RuntimeError("Agent completed without committing a terminal status")


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
    tracker = TokenTracker()

    agent_task = asyncio.create_task(
      run_agent_loop(
        agent,
        new_message=HumanMessage(content=replace_surrogates(user_input)),
        record=record,
        token_tracker=tracker,
      )
    )

    record.task = agent_task

    try:
      await consume_agent_events(record, agent_task)

    except Exception as error:
      print(f"\nError: {error}")

    finally:
      await run_manager.release(record.run_id)


async def main():
  logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
  )
  # Avoid creating surrogate characters if a terminal sends malformed UTF-8.
  sys.stdin.reconfigure(encoding="utf-8", errors="replace")

  app_config = load_app_config()
  tool_registry = create_builtin_registry()
  tool_registry.register_many(await load_mcp_tools(app_config.mcp))
  model = create_chat_model(app_config.model)

  async with make_sqlite_checkpointer(checkpoint_db_path) as checkpointer:
    agent = create_lead_agent(
      model=model,
      tool_registry=tool_registry,
      checkpointer=checkpointer,
    )
    await run_interactive_loop(agent)


if __name__ == "__main__":
  asyncio.run(main())
