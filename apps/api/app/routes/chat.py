"""Chat routes — SSE streaming and non-streaming endpoints."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import AsyncIterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from langchain.chat_models import init_chat_model

from app.agent import get_agent, Agent
from app.agent.tools import ToolRegistry
from app.agent.skills import SkillRegistry, Skill
from app.agent.mcp import MCPClientManager, MCPServerConfig
from app.models.schemas import ChatRequest, ChatResponse


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


def _build_default_agent(model: str) -> Agent:
    """Build a default agent with built-in tools and no MCP."""
    tool_registry = ToolRegistry()

    from app.agent.tools.builtin import web_search, read_local_file

    tool_registry.register(web_search)
    tool_registry.register(read_local_file)

    return Agent(
        model=model,
        tools=tool_registry,
        system_prompt=(
            "You are Shikigen, a helpful AI assistant. "
            "You have access to tools for web search and file reading. "
            "Use tools when they help answer the user's question. "
            "Be concise and helpful."
        ),
    )


async def _stream_chat(agent: Agent, messages: list, system_prompt: str | None) -> AsyncIterator[str]:
    """Stream chat response via SSE."""
    graph = agent.build()

    # Convert messages to LangChain format
    input_messages = []
    for m in messages:
        if m.get("role") == "user":
            input_messages.append({"role": "user", "content": m["content"]})
        elif m.get("role") == "assistant":
            input_messages.append({"role": "assistant", "content": m["content"]})

    config = {"configurable": {"thread_id": "default"}}

    try:
        async for event in graph.astream_events(
            {"messages": input_messages},
            config=config,
            version="v2",
        ):
            kind = event.get("event", "")

            if kind == "on_chat_model_stream":
                content = event.get("data", {}).get("chunk", {}).get("content", "")
                if content:
                    yield f"data: {json.dumps({'type': 'token', 'content': content})}\n\n"

            elif kind == "on_tool_start":
                name = event.get("name", "unknown")
                tool_input = event.get("data", {}).get("input", {})
                yield f"data: {json.dumps({'type': 'tool_call', 'tool_name': name, 'tool_input': tool_input})}\n\n"

            elif kind == "on_tool_end":
                output = event.get("data", {}).get("output", "")
                yield f"data: {json.dumps({'type': 'tool_result', 'content': str(output)})}\n\n"

        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    except Exception as e:
        logger.exception("Chat stream error")
        yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"


@router.post("/chat")
async def chat(req: ChatRequest):
    """Chat endpoint — SSE streaming by default."""
    model_name = req.model or os.getenv("MODEL", "deepseek/deepseek-v4-pro")

    agent = get_agent()
    if agent is None:
        agent = _build_default_agent(model_name)

    if req.stream:
        return StreamingResponse(
            _stream_chat(agent, [m.model_dump() for m in req.messages], req.system_prompt),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    else:
        # Non-streaming response
        graph = agent.build()
        input_messages = [
            {"role": m["role"], "content": m["content"]}
            for m in [msg.model_dump() for msg in req.messages]
        ]
        config = {"configurable": {"thread_id": "default"}}

        result = await graph.ainvoke({"messages": input_messages}, config=config)
        last_msg = result["messages"][-1]
        return ChatResponse(
            content=getattr(last_msg, "content", str(last_msg)),
        )


@router.get("/health")
async def health() -> dict[str, str]:
    """Health check — used for heartbeat polling."""
    return {"status": "ok"}
