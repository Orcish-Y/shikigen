import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.filesystem import grep, list_dir, read_file, write_file


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

  def test_lists_files_and_directories_in_name_order(self) -> None:
    with tempfile.TemporaryDirectory() as temporary_directory:
      workspace = Path(temporary_directory).resolve()
      (workspace / "zebra.txt").write_text("", encoding="utf-8")
      (workspace / "alpha").mkdir()

      with patch("tools.filesystem.WORKSPACE_ROOT", workspace):
        result = list_dir.invoke({"path": "."})

      self.assertEqual(result, "alpha/\nzebra.txt")

  def test_reports_empty_directory_and_non_directory_separately(self) -> None:
    with tempfile.TemporaryDirectory() as temporary_directory:
      workspace = Path(temporary_directory).resolve()
      (workspace / "empty").mkdir()
      (workspace / "file.txt").write_text("", encoding="utf-8")

      with patch("tools.filesystem.WORKSPACE_ROOT", workspace):
        empty_result = list_dir.invoke({"path": "empty"})
        file_result = list_dir.invoke({"path": "file.txt"})

      self.assertEqual(empty_result, "(empty)")
      self.assertEqual(file_result, "Error: Not a directory: file.txt")

  def test_grep_skips_noise_directories_and_non_utf8_files(self) -> None:
    with tempfile.TemporaryDirectory() as temporary_directory:
      workspace = Path(temporary_directory).resolve()
      (workspace / "source.py").write_text(
        "def read_file():\n  pass\n", encoding="utf-8"
      )
      (workspace / "binary.bin").write_bytes(b"\xff\xfe\x00")

      for directory_name in (".git", ".venv", "__pycache__"):
        directory = workspace / directory_name
        directory.mkdir()
        (directory / "noise.py").write_text("def read_file():\n", encoding="utf-8")

      with patch("tools.filesystem.WORKSPACE_ROOT", workspace):
        result = grep.invoke({"pattern": "def read_file"})

      self.assertEqual(result, "source.py:1:def read_file():")
