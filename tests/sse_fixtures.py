"""Decode our single-line SSE data frames in consumer tests."""

import json


def parse_sse(text: str) -> dict:
  frames = parse_sse_frames(text)
  if len(frames) != 1:
    raise AssertionError(f"Expected one SSE frame, got {len(frames)}")
  return frames[0]


def parse_sse_frames(text: str) -> list[dict]:
  frames = []
  for block in text.split("\n\n"):
    if not block:
      continue
    lines = block.splitlines()
    if (
      len(lines) != 2
      or not lines[0].startswith("event: ")
      or not lines[1].startswith("data: ")
    ):
      raise AssertionError(f"Invalid SSE frame: {block!r}")
    frames.append({"event": lines[0][7:], "data": json.loads(lines[1][6:])})
  return frames
