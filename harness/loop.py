import asyncio

from langchain_core.messages import BaseMessage

from harness.stream import Stream


async def run_agent_loop(
  agent,  # 编译好的 agent graph
  messages: list[BaseMessage],  # 当前消息历史（会被原地更新）
  *,
  run_id: str,
  stream: Stream,
  abort_event: asyncio.Event | None = None,
) -> None:
  """执行 agent，流式输出。

  对应用 deer-flow 的 _stream_once()。
  三个频道并发消费：messages（token 流）、tool_calls（工具调用）、values（状态同步）。

  执行完成后，messages 列表会被更新为最新的完整历史。
  """

  async def handle_values(event_stream: object) -> None:
    async for value in event_stream.values:
      messages[:] = value["messages"]

  async def handle_messages(event_stream: object) -> str:
    async for message in event_stream.messages:
      async for text_delta in message.text:
        stream.publish("message", {"text": text_delta})
    stream.publish("message", {"text": "\n"})

  async def handle_tool_calls(event_stream: object) -> None:
    async for call in event_stream.tool_calls:
      # 消费完增量后，call.output 才是完整的工具输出。
      async for _ in call.output_deltas:
        pass

      stream.publish(
        "tool_call",
        {
          "name": call.tool_name,
          "input": call.input,
          "output": call.output,
        },
      )

  async def grouped_task_events(stream):
    async with asyncio.TaskGroup() as group:
      group.create_task(handle_values(stream))
      group.create_task(handle_messages(stream))
      group.create_task(handle_tool_calls(stream))

  abort_task = asyncio.create_task(abort_event.wait())

  try:
    async with await agent.astream_events(
      {"messages": messages},
      version="v3",
    ) as event_stream:
      stream.publish("metadata", {"run_id": run_id})

      if abort_event is None:
        # await asyncio.gather(*get_event(event_stream))
        await asyncio.create_task(grouped_task_events(event_stream))
        stream.publish("status", {"status": "completed"})
        return

      consume_future = asyncio.create_task(grouped_task_events(event_stream))

      done, pending = await asyncio.wait(
        {consume_future, abort_task},
        return_when=asyncio.FIRST_COMPLETED,
      )

      for task in pending:
        task.cancel()

      if consume_future in done:
        await consume_future
        stream.publish("status", {"status": "completed"})
      else:
        await asyncio.gather(consume_future, return_exceptions=True)
        stream.publish("status", {"status": "cancelled"})
  except Exception as error:
    stream.publish("error", {"message": str(error)})
    raise
  finally:
    stream.close()
    for task in (consume_future, abort_task):
      if not task.done():
        task.cancel()

    await asyncio.gather(
      consume_future,
      abort_task,
      return_exceptions=True,
    )
