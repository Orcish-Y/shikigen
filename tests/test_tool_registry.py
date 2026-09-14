import unittest
from unittest.mock import Mock

from shikigen.tools import ToolRegistry, create_builtin_registry


def tool_named(name: str) -> Mock:
  tool = Mock()
  tool.name = name
  return tool


class ToolRegistryTests(unittest.TestCase):
  def test_excluding_preserves_source_order_and_tool_identity(self) -> None:
    first, second, third = [tool_named(name) for name in ("a", "b", "c")]
    registry = ToolRegistry().register_many([first, second, third])

    filtered = registry.excluding(name for name in ("b", "missing"))

    self.assertEqual(registry.list(), [first, second, third])
    self.assertEqual(filtered.list(), [first, third])
    self.assertIs(filtered.list()[0], first)
    filtered.register(tool_named("d"))
    self.assertEqual(registry.names, ["a", "b", "c"])

  def test_excluding_all_or_no_tools_returns_independent_registry(self) -> None:
    registry = ToolRegistry().register(tool_named("a"))
    self.assertEqual(registry.excluding(["a"]).list(), [])
    copied = registry.excluding([])
    self.assertIsNot(copied, registry)
    self.assertEqual(copied.list(), registry.list())

  def test_register_skips_duplicate_and_logs_a_warning(self) -> None:
    registry = ToolRegistry()
    first = tool_named("same_name")
    duplicate = tool_named("same_name")

    with self.assertLogs("shikigen.tools", level="WARNING") as logs:
      result = registry.register(first).register(duplicate)

    self.assertIs(result, registry)
    self.assertEqual(registry.list(), [first])
    self.assertIn("skipping duplicate", logs.output[0])

  def test_register_many_skips_duplicates(self) -> None:
    registry = ToolRegistry()
    first = tool_named("same_name")
    duplicate = tool_named("same_name")

    with self.assertLogs("shikigen.tools", level="WARNING"):
      registry.register_many([first, duplicate])

    self.assertEqual(registry.list(), [first])

  def test_registries_do_not_share_tools(self) -> None:
    first_registry = ToolRegistry().register(tool_named("first"))
    second_registry = ToolRegistry()

    self.assertEqual(first_registry.names, ["first"])
    self.assertEqual(second_registry.names, [])


class BuiltinToolRegistryTests(unittest.TestCase):
  def test_builtin_registry_includes_filesystem_tools(self) -> None:
    registry = create_builtin_registry()

    self.assertIn("read_file", registry.names)
    self.assertIn("write_file", registry.names)
