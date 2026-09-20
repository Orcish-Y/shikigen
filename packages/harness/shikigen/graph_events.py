"""LangGraph v3 events to project messages; no storage or transport dependencies."""

from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from shikigen.messages import message_content, message_identity
from shikigen.stream import MessageData


class GraphEventAdapter:
  """Normalize root events and suppress identical snapshots within one invocation.

  This cache is not an ownership authority: storage decides cross-run identity.
  """

  def __init__(self) -> None:
    self._stream_id: str | None = None
    self._seen: dict[str, dict[str, Any]] = {}

  @staticmethod
  def _get_params(event: object, method: str) -> dict[str, Any] | None:
    if not isinstance(event, dict) or event.get("method") != method:
      return None
    params = event.get("params")
    if not isinstance(params, dict) or params.get("namespace") != []:
      return None
    return params

  def delta(self, event: object) -> MessageData | None:
    params = self._get_params(event, "messages")
    if params is None:
      return None
    data = params.get("data")
    if not isinstance(data, (tuple, list)) or not data:
      raise ValueError("Invalid Graph message event")
    chunk = data[0]
    if isinstance(chunk, AIMessage):
      if not chunk.id or not chunk.id.strip():
        raise ValueError("Graph preview requires a stable message ID")
      if chunk.text:
        return {"message_id": chunk.id, "text": chunk.text, "done": False}
      return None
    # Human/tool framework messages are represented by complete root values.
    if not isinstance(chunk, dict):
      return None
    kind = chunk.get("event")
    if kind == "message-start":
      self._stream_id = None
      if chunk.get("role") in {"ai", "assistant"}:
        identity = chunk.get("id")
        if not isinstance(identity, str) or not identity.strip():
          raise ValueError("Graph preview requires a stable message ID")
        self._stream_id = identity
    elif kind == "message-finish":
      identity, self._stream_id = self._stream_id, None
      if identity is not None:
        return {"message_id": identity, "text": "", "done": True}
    elif kind in {"content-block-start", "content-block-delta"}:
      block = chunk.get("content" if kind == "content-block-start" else "delta")
      if not isinstance(block, dict):
        raise ValueError("Invalid Graph content block")
      if block.get("type") in {"text", "text-delta"}:
        text = block.get("text")
        if not isinstance(text, str) or self._stream_id is None:
          raise ValueError("Graph text requires message identity and text")
        if text:
          return {"message_id": self._stream_id, "text": text, "done": False}
    return None

  def messages(self, event: object) -> list[dict[str, Any]]:
    params = self._get_params(event, "values")
    if params is None:
      return []
    values = params.get("data")
    if not isinstance(values, dict):
      raise ValueError("Invalid root Graph values")
    messages = values.get("messages", [])
    if not isinstance(messages, (list, tuple)):
      raise ValueError("Invalid root messages")
    result = []
    for raw in messages:
      if not isinstance(raw, (HumanMessage, AIMessage, ToolMessage)):
        continue
      content = message_content(raw)
      key = message_identity(content)[1]
      existing = self._seen.get(key)
      if existing is not None:
        if existing != content:
          raise ValueError("Graph reused message identity with different content")
        continue
      self._seen[key] = content
      result.append(content)
    return result
