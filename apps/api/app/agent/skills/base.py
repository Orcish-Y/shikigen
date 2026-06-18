"""Skill dataclass."""

from dataclasses import dataclass, field
from typing import Any, Callable

from langchain_core.tools import BaseTool


@dataclass
class Skill:
    """A reusable agent capability.

    Attributes:
        name: Unique skill identifier.
        description: Short description of what the skill does.
        prompt: Instructions injected into the agent's system prompt.
        tools: Additional tools provided by this skill.
        subagent_profile: DeepAgents subagent profile name, if applicable.
    """

    name: str
    description: str
    prompt: str = ""
    tools: list[BaseTool | Callable] = field(default_factory=list)
    subagent_profile: str | None = None

    def to_tool(self) -> BaseTool | None:
        """Optionally expose this skill as a tool the agent can invoke."""
        return None
