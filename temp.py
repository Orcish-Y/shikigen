import asyncio

from shikigen.agent import create_lead_agent
from shikigen.app_config import load_app_config
from shikigen.model import create_chat_model


async def print_messages(stream):
  async for item in stream.messages:
    async for token in item.text:
      print(token, end="", flush=True)


async def print_tool_calls(stream):
  async for item in stream.tool_calls:
    print(f"\nTool call: {item.tool_name}({item.input})")

    async for delta in item.output_deltas:
      print(delta, end="", flush=True)

    print(f"\nTool result: {item.output}")


async def main():
  agent = create_lead_agent(create_chat_model(load_app_config().model))
  async with await agent.astream_events(
    {"messages": [{"role": "user", "content": "使用 add 工具，计算150 + 1"}]},
    config={"configurable": {"thread_id": "stream-example"}},
    version="v3",
  ) as stream:
    await asyncio.gather(
      print_messages(stream),
      print_tool_calls(stream),
    )


if __name__ == "__main__":
  asyncio.run(main())
