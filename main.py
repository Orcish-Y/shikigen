import asyncio
import logging
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv
from langchain.messages import HumanMessage
from langchain_core.messages import BaseMessage

from harness import StreamManager, create_lead_agent, run_agent_loop
from harness.stream import MessageData, ToolCallData
from text_safety import replace_surrogates

load_dotenv()
agent = create_lead_agent(
  model="deepseek:deepseek-v4-flash",
)

messages: list[BaseMessage] = []
output_path = Path("output.json")


def consume_messages(message: MessageData) -> None:
  print(message["text"], end="", flush=True)


def consume_tool_calls(call: ToolCallData) -> None:
  print(f"\nTool call: {call['name']}({call['input']})")
  print(f"\nTool result: {call['output']}")


stream_manager = StreamManager()


async def main():
  logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
  )
  # Avoid creating surrogate characters if a terminal sends malformed UTF-8.
  sys.stdin.reconfigure(encoding="utf-8", errors="replace")
  print("你好主人，有什么可以帮助你的？\n")

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
    messages.append(HumanMessage(content=replace_surrogates(user_input)))
    run_id = str(uuid.uuid4())
    stream = stream_manager.create(run_id)
    abort_event = asyncio.Event()

    agent_task = asyncio.create_task(
      run_agent_loop(
        agent,
        messages,
        stream=stream,
        run_id=run_id,
        abort_event=abort_event,
      )
    )

    try:
      async for event in stream.subscribe():
        if event.event == "message":
          consume_messages(event.data)
        elif event.event == "tool_call":
          consume_tool_calls(event.data)
      await agent_task
    finally:
      stream_manager.remove(run_id)


if __name__ == "__main__":
  asyncio.run(main())
