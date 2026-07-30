import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv
from langchain.messages import HumanMessage
from langchain_core.messages import BaseMessage

from harness import create_lead_agent, run_agent_loop
from text_safety import replace_surrogates

load_dotenv()
agent = create_lead_agent(
  model="deepseek:deepseek-v4-flash",
)

messages: list[BaseMessage] = []
output_path = Path("output.json")


async def print_tool_call(call: object) -> None:
  """Print a tool call and its asynchronously streamed output."""
  print(f"\nTool call: {call.tool_name}({call.input})")
  async for delta in call.output_deltas:
    print(delta, end="", flush=True)
  print(f"\nTool result: {call.output}")


async def consume_messages(message: str) -> None:
  print(message, end="", flush=True)


async def consume_tool_calls(call: object) -> None:
  await print_tool_call(call)


async def main():
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
    await run_agent_loop(
      agent, messages, on_message=consume_messages, on_tool_call=consume_tool_calls
    )


if __name__ == "__main__":
  asyncio.run(main())
