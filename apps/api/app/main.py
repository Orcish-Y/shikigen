"""Shikigen API — FastAPI backend with LangChain DeepAgents."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

app = FastAPI(title="Shikigen API", version="0.0.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health() -> dict[str, str]:
    """Health check endpoint for heartbeat polling."""
    return {"status": "ok"}


@app.post("/api/chat")
async def chat(body: dict) -> dict[str, str]:
    """Chat endpoint — placeholder for DeepAgents integration."""
    messages = body.get("messages", [])
    last_message = messages[-1]["content"] if messages else ""

    # TODO: Integrate LangChain DeepAgents here
    return {"role": "assistant", "content": f"Echo: {last_message}"}
