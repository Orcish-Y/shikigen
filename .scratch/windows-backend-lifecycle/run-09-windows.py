"""Run all Windows acceptance, keeping earlier tickets' evidence untouched."""

import sys
import unittest
from pathlib import Path

repo = Path(__file__).resolve().parents[2]
tests = repo / "frontend/src-tauri/tests"
suite = unittest.defaultTestLoader.discover(str(tests), pattern="*_acceptance.py")


def route_artifacts(items):
  for item in items:
    if isinstance(item, unittest.TestSuite):
      route_artifacts(item)
    elif (
      hasattr(type(item), "artifact_root") and type(item).__name__ != "ClientAcceptance"
    ):
      type(item).artifact_root = (
        repo
        / ".scratch/windows-backend-lifecycle/client-regression"
        / type(item).__name__
      )


route_artifacts(suite)
result = unittest.TextTestRunner(verbosity=2).run(suite)
sys.exit(not result.wasSuccessful())
