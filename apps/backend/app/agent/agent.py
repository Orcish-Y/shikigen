"""Agent core — DeepAgents factory with tools, skills, and MCP integration."""

from typing import Any

from app.agent.middlewares.toolTtracking import ToolTtrackingMiddleware
from deepagents import create_deep_agent
from deepagents.backends import StateBackend
from langchain.chat_models import BaseChatModel

from .tools.registry import ToolRegistry
from .skills.registry import SkillRegistry
from .mcp.client import MCPClientManager


class Agent:
    """A full-featured AI agent with tools, skills, and MCP support."""

    def __init__(
        self,
        model: BaseChatModel | str,
        *,
        system_prompt: str | None = None,
        tools: ToolRegistry | None = None,
        skills: SkillRegistry | None = None,
        mcp: MCPClientManager | None = None,
        backend: Any = None,
        checkpointer: Any = None,
        interrupt_on: dict[str, bool] | None = None,
    ):
        self.model = model
        self.system_prompt = system_prompt
        self.tool_registry = tools or ToolRegistry()
        self.skill_registry = skills or SkillRegistry()
        self.mcp_manager = mcp or MCPClientManager()
        self._backend = backend
        self._checkpointer = checkpointer
        self._interrupt_on = interrupt_on

    async def start(self) -> None:
        """Initialize MCP connections and load skills."""
        await self.mcp_manager.connect_all()

    async def stop(self) -> None:
        """Shutdown MCP connections."""
        await self.mcp_manager.disconnect_all()

    def build(self) -> Any:
        """Build the compiled agent graph.

        Returns a LangGraph CompiledStateGraph ready for invocation.
        """
        extra_tools = [
            *self.tool_registry.get_tools(),
            *self.mcp_manager.get_tools(),
        ]

        skill_names = self.skill_registry.get_skill_names()

        return create_deep_agent(
            model=self.model,
            tools=extra_tools if extra_tools else None,
            system_prompt=self.system_prompt,
            skills=skill_names if skill_names else None,
            backend=self._backend or StateBackend(),
            checkpointer=self._checkpointer,
            middleware=[ToolTtrackingMiddleware()],
            # interrupt_on=self._interrupt_on,
        )


# Global agent instance (lazy init)
_agent: Agent | None = None


def get_agent() -> Agent | None:
    return _agent


def set_agent(agent: Agent) -> None:
    global _agent
    _agent = agent
