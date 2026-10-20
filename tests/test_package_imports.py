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
          "import shikigen.core.graph_events; "
          "import shikigen.core.tool_registry; "
          "import shikigen.core.tool_assembly; "
          "import shikigen.core.subagents; "
          "import shikigen.core.mcp_loader; "
          "import shikigen.tool_execution.executor; "
          "import shikigen.tool_execution.adapter.http_execution; "
          "import shikigen.tool_execution.adapter.python_execution; "
          "import shikigen.tool_execution.adapter.mcp_execution; "
          "import shikigen.tool_execution.mcp.sessions; "
          "import shikigen.tool_execution.mcp.http; "
          "import shikigen.contracts.events; "
          "import shikigen.contracts.runs; "
          "import shikigen.contracts.stream; "
          "from shikigen.core.loop import execute_agent_loop; "
          "assert shikigen.execute_agent_loop is execute_agent_loop; "
          "from shikigen.persistence import ChatStore; "
          "from shikigen.runtime import Runtime, open_runtime, assemble_runtime; "
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
