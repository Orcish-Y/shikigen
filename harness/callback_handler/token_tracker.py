"""Track token usage reported by LangChain LLM callbacks."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler

from harness.stream import UsageData, UsageModelData

logger = logging.getLogger(__name__)


class TokenTracker(BaseCallbackHandler):
  """追踪每次 LLM 调用的 token 用量，按模型分拆。"""

  def __init__(self) -> None:
    super().__init__()
    self.total_input: int = 0
    self.total_output: int = 0
    self.calls: int = 0
    self.by_model: dict[str, UsageModelData] = {}

  async def on_llm_end(self, response: Any, **kwargs: Any) -> None:
    """Record one completed LLM call."""
    del kwargs

    llm_output = getattr(response, "llm_output", None) or {}
    model_name = llm_output.get("model_name")
    input_tokens = 0
    output_tokens = 0

    for message in self._iter_messages(response):
      usage = getattr(message, "usage_metadata", None) or {}
      input_tokens += usage.get("input_tokens", 0)
      output_tokens += usage.get("output_tokens", 0)

    if input_tokens == 0 and output_tokens == 0:
      token_usage = llm_output.get("token_usage", {})
      input_tokens = token_usage.get("prompt_tokens", 0)
      output_tokens = token_usage.get("completion_tokens", 0)

    self.total_input += input_tokens
    self.total_output += output_tokens
    self.calls += 1

    if model_name:
      entry = self.by_model.setdefault(
        str(model_name), {"input": 0, "output": 0, "calls": 0}
      )
      entry["input"] += input_tokens
      entry["output"] += output_tokens
      entry["calls"] += 1

    logger.debug(
      "LLM call #%d: %d in + %d out = %d tokens (%s)",
      self.calls,
      input_tokens,
      output_tokens,
      input_tokens + output_tokens,
      model_name or "unknown",
    )

  @staticmethod
  def _iter_messages(response: Any) -> Iterator[Any]:
    """Yield messages carried by an LLMResult's generations."""
    for generation in response.generations or []:
      for chunk in generation:
        message = getattr(chunk, "message", None)
        if message is not None:
          yield message

  @property
  def total_tokens(self) -> int:
    return self.total_input + self.total_output

  def summary(self) -> UsageData:
    """Return a serializable snapshot for the run event stream."""
    return {
      "total_input": self.total_input,
      "total_output": self.total_output,
      "total_tokens": self.total_tokens,
      "calls": self.calls,
      "by_model": {model: dict(data) for model, data in self.by_model.items()},
    }
