"""Skill system — reusable agent capabilities.

A Skill is a named bundle of:
- A prompt or instruction set
- Optional tools
- Optional sub-agents
"""

from .base import Skill
from .registry import SkillRegistry

__all__ = ["Skill", "SkillRegistry"]
