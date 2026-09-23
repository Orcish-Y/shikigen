"""完整产品消息：框架转换、稳定身份与不可变内容的共同边界。"""

from typing import Annotated, Any, Literal

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter


class StrictModel(BaseModel):
  model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


type Identity = Annotated[str, Field(min_length=1, pattern=r"\S")]


class HumanContent(StrictModel):
  type: Literal["human"]
  message_id: Identity
  content: str | list[str | dict[str, JsonValue]]


class ToolCall(StrictModel):
  id: Identity
  name: Identity
  args: dict[str, JsonValue]
  type: Literal["tool_call"] = "tool_call"


class AIContent(StrictModel):
  type: Literal["ai"]
  message_id: Identity
  content: str | list[str | dict[str, JsonValue]]
  tool_calls: list[ToolCall]


class ToolContent(StrictModel):
  type: Literal["tool"]
  message_id: Identity | None = None
  content: str | list[str | dict[str, JsonValue]]
  tool_call_id: Identity
  name: str | None = None
  status: Literal["success", "error"]
  artifact: JsonValue = None


type CompleteMessage = Annotated[
  HumanContent | AIContent | ToolContent, Field(discriminator="type")
]
MESSAGE = TypeAdapter(CompleteMessage)


def normalize_message(content: Any) -> dict[str, Any]:
  """保留省略与显式 null；工具框架 ID 不参与产品身份。"""
  validated_msg = MESSAGE.validate_python(content)
  msg_dict = validated_msg.model_dump(mode="json", exclude_unset=True)
  if isinstance(validated_msg, ToolContent):
    msg_dict["message_id"] = f"tool-result:{validated_msg.tool_call_id}"
  return msg_dict


def message_identity(content: Any) -> tuple[str, str]:
  message = normalize_message(content)
  kind = message["type"]
  identity = message["tool_call_id"] if kind == "tool" else message["message_id"]
  return f"{kind}_message", f"{kind}:{identity}"


def message_content(message: HumanMessage | AIMessage | ToolMessage) -> dict[str, Any]:
  content: dict[str, Any] = {
    "type": message.type,
    "message_id": message.id,
    "content": message.content,
  }
  if isinstance(message, AIMessage):
    content["tool_calls"] = message.tool_calls
  if isinstance(message, ToolMessage):
    content.update(
      tool_call_id=message.tool_call_id, name=message.name, status=message.status
    )
    if "artifact" in message.model_fields_set:
      content["artifact"] = message.artifact
  return normalize_message(content)
