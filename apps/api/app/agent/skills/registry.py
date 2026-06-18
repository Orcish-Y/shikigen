"""Skill registry — discovery and loading of skills."""

from .base import Skill


class SkillRegistry:
    """Registry for agent skills."""

    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}

    def register(self, skill: Skill) -> None:
        """Register a skill by name."""
        self._skills[skill.name] = skill

    def get(self, name: str) -> Skill | None:
        """Get a skill by name."""
        return self._skills.get(name)

    def get_skill_names(self) -> list[str]:
        """Return all registered skill names (for DeepAgents)."""
        return list(self._skills.keys())

    def list(self) -> list[Skill]:
        """Return all registered skills."""
        return list(self._skills.values())

    def remove(self, name: str) -> None:
        """Remove a skill by name."""
        self._skills.pop(name, None)
