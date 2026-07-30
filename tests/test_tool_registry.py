import unittest
from unittest.mock import Mock

from tools import ToolRegistry


def tool_named(name: str) -> Mock:
  tool = Mock()
  tool.name = name
  return tool


class ToolRegistryTests(unittest.TestCase):
  def test_register_skips_duplicate_and_logs_a_warning(self) -> None:
    registry = ToolRegistry()
    first = tool_named("same_name")
    duplicate = tool_named("same_name")

    with self.assertLogs("tools", level="WARNING") as logs:
      result = registry.register(first).register(duplicate)

    self.assertIs(result, registry)
    self.assertEqual(registry.list(), [first])
    self.assertIn("skipping duplicate", logs.output[0])

  def test_register_many_skips_duplicates(self) -> None:
    registry = ToolRegistry()
    first = tool_named("same_name")
    duplicate = tool_named("same_name")

    with self.assertLogs("tools", level="WARNING"):
      registry.register_many([first, duplicate])

    self.assertEqual(registry.list(), [first])

  def test_registries_do_not_share_tools(self) -> None:
    first_registry = ToolRegistry().register(tool_named("first"))
    second_registry = ToolRegistry()

    self.assertEqual(first_registry.names, ["first"])
    self.assertEqual(second_registry.names, [])
