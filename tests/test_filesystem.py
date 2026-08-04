import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.filesystem import read_file, write_file


class FilesystemToolTests(unittest.TestCase):
  def test_writes_and_reads_a_file_inside_the_workspace(self) -> None:
    with tempfile.TemporaryDirectory() as temporary_directory:
      workspace = Path(temporary_directory).resolve()
      with patch("tools.filesystem.WORKSPACE_ROOT", workspace):
        result = write_file.invoke({"path": "notes/example.txt", "content": "hello"})
        content = read_file.invoke({"path": "notes/example.txt"})

      self.assertEqual(result, "Successfully wrote to file notes/example.txt")
      self.assertEqual(content, "hello")

  def test_rejects_a_path_outside_the_workspace(self) -> None:
    with tempfile.TemporaryDirectory() as temporary_directory:
      workspace = Path(temporary_directory).resolve()
      outside_path = workspace.parent / "outside.txt"

      with patch("tools.filesystem.WORKSPACE_ROOT", workspace):
        with self.assertRaisesRegex(ValueError, "must stay within the workspace"):
          read_file.invoke({"path": str(outside_path)})
