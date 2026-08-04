import asyncio

from langchain_core.messages import HumanMessage

from harness.run_manager import RunRecord


async def run_agent_loop(
  agent,  # 编译好的 agent graph
  new_message: HumanMessage,
  *,
  record: RunRecord,
) -> None:
  """使用新消息执行 agent，由 checkpointer 恢复此前的完整状态。

  对应用 deer-flow 的 _stream_once()。
  并发消费 messages（token 流）和 tool_calls（工具调用）。
  """

  async def handle_messages(event_stream: object) -> None:
    async for message in event_stream.messages:
      async for text_delta in message.text:
        record.stream.publish("message", {"text": text_delta})
    record.stream.publish("message", {"text": "\n"})

  async def handle_tool_calls(event_stream: object) -> None:
    async for call in event_stream.tool_calls:
      # 消费完增量后，call.output 才是完整的工具输出。
      async for _ in call.output_deltas:
        pass

      record.stream.publish(
        "tool_call",
        {
          "name": call.tool_name,
          "input": call.input,
          "output": call.output,
        },
      )

  async def consume_event_stream(event_stream: object) -> None:
    async with asyncio.TaskGroup() as group:
      group.create_task(handle_messages(event_stream))
      group.create_task(handle_tool_calls(event_stream))

  consume_task: asyncio.Task[None] | None = None
  abort_task: asyncio.Task[bool] | None = None
  config = {"configurable": {"thread_id": record.thread_id}}
  try:
    async with await agent.astream_events(
      {"messages": [new_message]},
      config=config,
      version="v3",
    ) as event_stream:
      record.stream.publish("metadata", {"run_id": record.run_id})
      consume_task = asyncio.create_task(consume_event_stream(event_stream))

      abort_task = asyncio.create_task(record.abort_event.wait())

      done, pending = await asyncio.wait(
        {consume_task, abort_task},
        return_when=asyncio.FIRST_COMPLETED,
      )

      for task in pending:
        task.cancel()

      if consume_task in done:
        await consume_task
        record.stream.publish("status", {"status": "completed"})
      else:
        await asyncio.gather(consume_task, return_exceptions=True)
        record.stream.publish("status", {"status": "cancelled"})
  except Exception as error:
    record.stream.publish("error", {"message": str(error)})
    raise
  finally:
    record.stream.close()
    tasks = [task for task in (consume_task, abort_task) if task is not None]
    for task in tasks:
      if not task.done():
        task.cancel()

    if tasks:
      await asyncio.gather(*tasks, return_exceptions=True)
