from collections.abc import Awaitable, Callable
from typing import Any, Protocol, override

from langchain.agents.middleware import AgentMiddleware, AgentState, ToolCallRequest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.runtime import Runtime
from langgraph.types import Command

from shikigen.runtime_context import AgentRunContext


class MessageJournal(Protocol):
  """持久化中间件所需的最小接口，避免直接依赖具体的 ChatStore。"""

  async def append_event(
    self,
    *,
    thread_id: str,
    run_id: str,
    event_type: str,
    category: str,
    content: Any,
    metadata: dict[str, Any] | None = None,
    event_key: str | None = None,
  ) -> int: ...


def _context(runtime: Runtime[AgentRunContext]) -> AgentRunContext:
  # run 身份来自本次调用的 Runtime，而不是保存在共享 middleware 实例上。
  context = runtime.context
  if context is None:
    raise RuntimeError("Chat persistence requires AgentRunContext")
  return context


def _message_key(prefix: str, message: HumanMessage | AIMessage | ToolMessage) -> str:
  # 稳定 key 让 checkpoint 重放同一条消息时命中数据库幂等约束。
  if message.id:
    return f"{prefix}:{message.id}"
  if isinstance(message, ToolMessage):
    return f"{prefix}:{message.tool_call_id}"
  raise RuntimeError(f"{type(message).__name__} requires a stable message id")


def _tool_messages(result: ToolMessage | Command[Any]) -> list[ToolMessage]:
  """统一提取普通工具返回值和 Command.update 中携带的工具消息。"""
  if isinstance(result, ToolMessage):
    return [result]

  update = result.update
  if not isinstance(update, dict):
    return []

  messages = update.get("messages") or []
  if isinstance(messages, ToolMessage):
    return [messages]
  return [message for message in messages if isinstance(message, ToolMessage)]


class ChatPersistenceMiddleware(AgentMiddleware):
  """将 Agent 的完整消息投影到面向产品查询的 run journal。"""

  def __init__(self, journal: MessageJournal):
    self._journal = journal

  @override
  async def abefore_agent(
    self,
    state: AgentState,
    runtime: Runtime[AgentRunContext],
  ) -> None:
    messages = state.get("messages") or []
    # state 可能包含 checkpoint 恢复出的完整历史，这里只写本轮入口消息。
    if not messages or not isinstance(messages[-1], HumanMessage):
      return

    message = messages[-1]
    context = _context(runtime)
    await self._journal.append_event(
      thread_id=context.thread_id,
      run_id=context.run_id,
      event_type="human_message",
      category="message",
      event_key=_message_key("human", message),
      content={
        "type": "human",
        "content": message.content,
        "message_id": message.id,
      },
    )

  @override
  async def aafter_model(
    self,
    state: AgentState,
    runtime: Runtime[AgentRunContext],
  ) -> None:
    messages = state.get("messages") or []
    # after_model 得到的是完整 AIMessage；逐 token 输出仍由 stream 负责。
    if not messages or not isinstance(messages[-1], AIMessage):
      return

    message = messages[-1]
    context = _context(runtime)
    await self._journal.append_event(
      thread_id=context.thread_id,
      run_id=context.run_id,
      event_type="ai_message",
      category="message",
      event_key=_message_key("ai", message),
      content={
        "type": "ai",
        "content": message.content,
        "message_id": message.id,
        "tool_calls": message.tool_calls,
      },
    )

  @override
  async def awrap_tool_call(
    self,
    request: ToolCallRequest,
    handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
  ) -> ToolMessage | Command[Any]:
    # 等内层工具与错误处理中间件完成后，再持久化最终 ToolMessage。
    result = await handler(request)
    context = _context(request.runtime)
    for message in _tool_messages(result):
      await self._journal.append_event(
        thread_id=context.thread_id,
        run_id=context.run_id,
        event_type="tool_message",
        category="message",
        event_key=_message_key("tool", message),
        content={
          "type": "tool",
          "content": message.content,
          "message_id": message.id,
          "tool_call_id": message.tool_call_id,
          "name": message.name,
          "status": message.status,
        },
      )
    return result
