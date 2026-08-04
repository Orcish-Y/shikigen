import unittest
from types import SimpleNamespace

from harness.callback_handler import TokenTracker


class TokenTrackerTests(unittest.IsolatedAsyncioTestCase):
  async def test_tracks_usage_metadata_by_model(self) -> None:
    tracker = TokenTracker()
    response = SimpleNamespace(
      generations=[
        [
          SimpleNamespace(
            message=SimpleNamespace(
              usage_metadata={"input_tokens": 12, "output_tokens": 5}
            )
          )
        ]
      ],
      llm_output={"model_name": "new-model"},
    )

    await tracker.on_llm_end(response)

    self.assertEqual(
      tracker.summary(),
      {
        "total_input": 12,
        "total_output": 5,
        "total_tokens": 17,
        "calls": 1,
        "by_model": {"new-model": {"input": 12, "output": 5, "calls": 1}},
      },
    )

  async def test_tracks_legacy_token_usage(self) -> None:
    tracker = TokenTracker()
    response = SimpleNamespace(
      generations=[],
      llm_output={
        "model_name": "legacy-model",
        "token_usage": {"prompt_tokens": 8, "completion_tokens": 3},
      },
    )

    await tracker.on_llm_end(response)

    self.assertEqual(tracker.total_input, 8)
    self.assertEqual(tracker.total_output, 3)
    self.assertEqual(
      tracker.by_model["legacy-model"],
      {"input": 8, "output": 3, "calls": 1},
    )
