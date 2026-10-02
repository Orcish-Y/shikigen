import tempfile
import unittest
from contextlib import chdir
from pathlib import Path

from shikigen.tools.filesystem import create_filesystem_tools


class FilesystemToolTests(unittest.TestCase):
  def test_bound_tools_remain_in_their_workspace_after_cwd_changes(self) -> None:
    with tempfile.TemporaryDirectory() as directory:
      parent = Path(directory)
      first, second = parent / "first", parent / "second"
      first.mkdir()
      second.mkdir()
      with chdir(parent):
        tools = {t.name: t for t in create_filesystem_tools("first")}
      with chdir(second):
        tools["write_file"].invoke({"path": "note.txt", "content": "first"})
        self.assertEqual(tools["read_file"].invoke({"path": "note.txt"}), "first")
        tools["bash"].invoke({"command": "echo first > shell.txt"})
      self.assertTrue((first / "shell.txt").is_file())
      self.assertEqual(list(second.iterdir()), [])

  def test_workspace_root_must_be_an_existing_directory(self) -> None:
    with tempfile.TemporaryDirectory() as directory:
      parent = Path(directory)
      file = parent / "file.txt"
      file.write_text("file", encoding="utf-8")
      for path in (file, parent / "missing"):
        with (
          self.subTest(path=path),
          self.assertRaisesRegex(ValueError, "existing directory"),
        ):
          create_filesystem_tools(path)

  def test_shell_runs_in_workspace(self) -> None:
    with tempfile.TemporaryDirectory() as temporary_directory:
      workspace = Path(temporary_directory).resolve()
      tools = {tool.name: tool for tool in create_filesystem_tools(workspace)}
      tools["bash"].invoke({"command": "echo migration-ok > shell-output.txt"})
      self.assertEqual(
        (workspace / "shell-output.txt").read_text().strip(), "migration-ok"
      )

  def test_writes_and_reads_a_file_inside_the_workspace(self) -> None:
    with tempfile.TemporaryDirectory() as temporary_directory:
      workspace = Path(temporary_directory).resolve()
      tools = {tool.name: tool for tool in create_filesystem_tools(workspace)}
      result = tools["write_file"].invoke(
        {"path": "notes/example.txt", "content": "hello"}
      )
      content = tools["read_file"].invoke({"path": "notes/example.txt"})

      self.assertEqual(result, "Successfully wrote to file notes/example.txt")
      self.assertEqual(content, "hello")

  def test_rejects_a_path_outside_the_workspace(self) -> None:
    with tempfile.TemporaryDirectory() as temporary_directory:
      workspace = Path(temporary_directory).resolve()
      outside_path = workspace.parent / "outside.txt"

      tools = {tool.name: tool for tool in create_filesystem_tools(workspace)}
      with self.assertRaisesRegex(ValueError, "must stay within the workspace"):
        tools["read_file"].invoke({"path": str(outside_path)})

  def test_lists_files_and_directories_in_name_order(self) -> None:
    with tempfile.TemporaryDirectory() as temporary_directory:
      workspace = Path(temporary_directory).resolve()
      (workspace / "zebra.txt").write_text("", encoding="utf-8")
      (workspace / "alpha").mkdir()

      tools = {tool.name: tool for tool in create_filesystem_tools(workspace)}
      result = tools["list_dir"].invoke({"path": "."})

      self.assertEqual(result, "alpha/\nzebra.txt")

  def test_reports_empty_directory_and_non_directory_separately(self) -> None:
    with tempfile.TemporaryDirectory() as temporary_directory:
      workspace = Path(temporary_directory).resolve()
      (workspace / "empty").mkdir()
      (workspace / "file.txt").write_text("", encoding="utf-8")

      tools = {tool.name: tool for tool in create_filesystem_tools(workspace)}
      empty_result = tools["list_dir"].invoke({"path": "empty"})
      file_result = tools["list_dir"].invoke({"path": "file.txt"})

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

      tools = {tool.name: tool for tool in create_filesystem_tools(workspace)}
      result = tools["grep"].invoke({"pattern": "def read_file"})

      self.assertEqual(result, "source.py:1:def read_file():")
