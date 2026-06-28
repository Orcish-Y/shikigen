"""Request and response schemas."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    """A single chat message."""

    role: Literal["user", "assistant", "system", "tool"]
    content: str
    tool_call_id: str | None = None
    name: str | None = None


class ChatRequest(BaseModel):
    """Request body for /api/chat."""

    messages: list[ChatMessage]
    model: str | None = Field(
        default=None,
        description="Model string in 'provider:name' format (e.g. 'anthropic:claude-sonnet-4-6')",
    )
    stream: bool = Field(default=True, description="Whether to stream the response via SSE")
    system_prompt: str | None = None


class ChatResponse(BaseModel):
    """Non-streaming chat response."""

    role: Literal["assistant"] = "assistant"
    content: str
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)


class ToolCallEvent(BaseModel):
    """SSE event: agent is invoking a tool."""

    type: Literal["tool_call"] = "tool_call"
    tool_name: str
    tool_input: dict[str, Any]
    tool_call_id: str


class ToolResultEvent(BaseModel):
    """SSE event: tool invocation result."""

    type: Literal["tool_result"] = "tool_result"
    tool_call_id: str
    content: str


class TokenEvent(BaseModel):
    """SSE event: streaming text token."""

    type: Literal["token"] = "token"
    content: str


class ThinkingEvent(BaseModel):
    """SSE event: agent reasoning/thinking."""

    type: Literal["thinking"] = "thinking"
    content: str


class DoneEvent(BaseModel):
    """SSE event: conversation turn complete."""

    type: Literal["done"] = "done"


class ErrorEvent(BaseModel):
    """SSE event: error occurred."""

    type: Literal["error"] = "error"
    message: str
    code: str | None = None
