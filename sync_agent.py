import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.messages import HumanMessage, SystemMessage
from langchain_core.load import dumpd
from langchain_core.messages import BaseMessage

from text_safety import replace_surrogates
from tools.add import add
from tools.get_current_time import get_current_time

load_dotenv()
agent = create_agent(
  model="deepseek:deepseek-v4-flash",
  system_prompt="你是一个柔情猫娘，你的名字叫柔爪。",
  tools=[get_current_time, add],
)

messages: list[BaseMessage] = [
  SystemMessage(os.getenv("SYSTEM_PROMPT", "You are a helpful assistant."))
]
output_path = Path("output.json")


def append_output(item: object) -> None:
  """Append a stream value while keeping output.json as a valid JSON array."""
  if output_path.exists() and output_path.stat().st_size:
    with output_path.open(encoding="utf-8") as file:
      output = json.load(file)
  else:
    output = []

  output.append(dumpd(item))
  with output_path.open("w", encoding="utf-8") as file:
    json.dump(output, file, ensure_ascii=False, indent=2)


def main():
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

    stream = agent.stream_events(
      {"messages": messages},
      version="v3",
    )

    for kind, item in stream.interleave("messages", "tool_calls", "values"):
      if kind == "messages":
        for token in item.text:
          print(token, end="", flush=True)
      elif kind == "tool_calls":
        print(f"\nTool call: {item.tool_name}({item.input})")
        for delta in item.output_deltas:
          print(delta, end="", flush=True)
        print(f"\nTool result: {item.output}")
      elif kind == "values":
        if item["messages"][-1].type == "assistant":
          print("\n")
        messages[:] = item["messages"]

    # Token streaming deliberately suppresses newlines; restore the prompt line.
    print()


if __name__ == "__main__":
  main()
