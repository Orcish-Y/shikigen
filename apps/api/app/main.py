"""Shikigen API — FastAPI backend with LangChain DeepAgents."""

import logging

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

from app.routes.chat import router as chat_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Shikigen API", version="0.0.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router)


@app.on_event("startup")
async def startup() -> None:
    """Initialize agent on startup."""
    logger.info("Shikigen API starting up…")


@app.on_event("shutdown")
async def shutdown() -> None:
    """Cleanup on shutdown."""
    from app.agent import get_agent

    agent = get_agent()
    if agent:
        await agent.stop()
    logger.info("Shikigen API shut down.")
