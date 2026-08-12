import subprocess
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class PackageImportTests(unittest.TestCase):
  def test_tools_imports_in_a_fresh_process(self) -> None:
    result = subprocess.run(
      [sys.executable, "-c", "import tools"],
      cwd=PROJECT_ROOT,
      capture_output=True,
      text=True,
      check=False,
    )

    self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
  unittest.main()
