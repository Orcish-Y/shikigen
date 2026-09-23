from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AgentRunContext:
  """Business identity for one top-level agent invocation."""

  thread_id: str
  run_id: str
