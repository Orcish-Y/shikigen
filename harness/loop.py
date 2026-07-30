import asyncio

from langchain_core.messages import BaseMessage


async def run_agent_loop(
  agent,  # 编译好的 agent graph
  messages: list[BaseMessage],  # 当前消息历史（会被原地更新）
  *,
  on_message=None,  # 可选：token 级回调 (text: str)
  on_tool_call=None,  # 可选：工具调用回调 (call: ToolCallEvent)
) -> None:
  """执行 agent，流式输出。

  对应用 deer-flow 的 _stream_once()。
  三个频道并发消费：messages（token 流）、tool_calls（工具调用）、values（状态同步）。

  执行完成后，messages 列表会被更新为最新的完整历史。
  """

  async def on_values(event_stream: object) -> None:
    async for value in event_stream.values:
      messages[:] = value["messages"]

  async def handle_messages(event_stream: object) -> str:
    async for message in event_stream.messages:
      await on_message(await message.text)
    await on_message("\n")

  async def handle_tool_calls(event_stream: object) -> None:
    async for call in event_stream.tool_calls:
      await on_tool_call(call)

  def get_event(stream) -> list:
    event = [on_values(stream)]
    if on_message:
      event.append(handle_messages(stream))
    if on_tool_call:
      event.append(handle_tool_calls(stream))
    return event

  async with await agent.astream_events(
    {"messages": messages},
    version="v3",
  ) as stream:
    await asyncio.gather(*get_event(stream))
