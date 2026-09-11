import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class PackageImportTests(unittest.TestCase):
  def test_tools_imports_in_a_fresh_process(self) -> None:
    result = subprocess.run(
      [sys.executable, "-c", "import shikigen.tools"],
      cwd=PROJECT_ROOT,
      capture_output=True,
      text=True,
      check=False,
    )

    self.assertEqual(result.returncode, 0, result.stderr)

  def test_installed_harness_imports_outside_project(self) -> None:
    with tempfile.TemporaryDirectory() as directory:
      result = subprocess.run(
        [
          sys.executable,
          "-I",
          "-c",
          "import shikigen; import shikigen.tools; "
          "import shikigen.middleware.chat_persistence_middleware; "
          "import shikigen.utils.text_safety",
        ],
        cwd=directory,
        capture_output=True,
        text=True,
        check=False,
      )

    self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
  unittest.main()
