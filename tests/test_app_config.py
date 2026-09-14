import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shikigen.app_config import (
  AppConfigError,
  HttpMcpServerConfig,
  StdioMcpServerConfig,
  load_app_config,
)


class AppConfigTests(unittest.TestCase):
  def test_subagent_policies_preserve_null_empty_and_reject_typos(self):
    from pydantic import ValidationError
    from shikigen.app_config import AppConfig

    config = AppConfig.model_validate(
      {
        "model": {},
        "mcp": {},
        "subagents": {
          "general": {"tools": []},
          "bash": {"tools": None, "disallowed_tools": ["write_file"]},
        },
      }
    )
    self.assertEqual(config.subagents.general.tools, [])
    self.assertIsNone(config.subagents.bash.tools)
    self.assertEqual(config.subagents.bash.disallowed_tools, ["write_file"])
    for invalid in (
      {"typo": {}},
      {"bash": {"tool": []}},
      {"general": {"tools": [""]}},
      {"general": {"disallowed_tools": None}},
    ):
      with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
        AppConfig.model_validate({"model": {}, "mcp": {}, "subagents": invalid})

  def write_config(self, directory: str, content: object) -> Path:
    path = Path(directory) / "config.json"
    path.write_text(json.dumps(content), encoding="utf-8")
    return path

  def test_loads_nested_mcp_config(self) -> None:
    with tempfile.TemporaryDirectory() as directory:
      path = self.write_config(
        directory,
        {
          "model": {"default": "example-model", "provider": "example"},
          "mcp": {
            "servers": {
              "example": {
                "transport": "http",
                "url": "https://example.com/mcp/",
              }
            }
          },
        },
      )

      config = load_app_config(path)

    self.assertEqual(config.model.default, "example-model")
    self.assertEqual(config.model.provider, "example")
    self.assertEqual(config.mcp.servers["example"].transport, "http")

  def test_loads_complete_model_config(self) -> None:
    with tempfile.TemporaryDirectory() as directory:
      path = self.write_config(
        directory,
        {
          "model": {
            "default": "configured-model",
            "provider": "configured-provider",
            "base_url": "https://models.example.com/v1",
          },
          "mcp": {},
        },
      )
      model = load_app_config(path).model

    self.assertEqual(model.default, "configured-model")
    self.assertEqual(model.provider, "configured-provider")
    self.assertEqual(model.base_url, "https://models.example.com/v1")

  def test_model_config_uses_current_defaults(self) -> None:
    with tempfile.TemporaryDirectory() as directory:
      path = self.write_config(directory, {"model": {}, "mcp": {}})

      config = load_app_config(path)

    self.assertEqual(config.model.default, "deepseek-v4-flash")
    self.assertEqual(config.model.provider, "deepseek")
    self.assertEqual(config.database.path, ".shikigen/data/shikigen.db")

  def test_mcp_config_uses_default_initial_max_attempts(self) -> None:
    with tempfile.TemporaryDirectory() as directory:
      path = self.write_config(directory, {"model": {}, "mcp": {}})

      config = load_app_config(path)

    self.assertEqual(config.mcp.initial_max_attempts, 3)

  def test_loads_initial_max_attempts(self) -> None:
    with tempfile.TemporaryDirectory() as directory:
      path = self.write_config(
        directory,
        {"model": {}, "mcp": {"initial_max_attempts": 5}},
      )

      config = load_app_config(path)

    self.assertEqual(config.mcp.initial_max_attempts, 5)

  def test_rejects_non_positive_initial_max_attempts(self) -> None:
    with tempfile.TemporaryDirectory() as directory:
      path = self.write_config(
        directory,
        {"model": {}, "mcp": {"initial_max_attempts": 0}},
      )

      with self.assertRaisesRegex(
        AppConfigError,
        r"(?s)initial_max_attempts.*greater than or equal to 1",
      ):
        load_app_config(path)

  def test_loads_stdio_server_config(self) -> None:
    with tempfile.TemporaryDirectory() as directory:
      path = self.write_config(
        directory,
        {
          "model": {},
          "mcp": {
            "servers": {
              "local": {
                "transport": "stdio",
                "command": "uvx",
                "args": ["example-mcp-server"],
              }
            }
          },
        },
      )

      config = load_app_config(path)

    server = config.mcp.servers["local"]
    assert isinstance(server, StdioMcpServerConfig)
    self.assertEqual(server.transport, "stdio")
    self.assertEqual(server.command, "uvx")
    self.assertEqual(server.args, ["example-mcp-server"])

  def test_uses_project_root_config_by_default(self) -> None:
    with tempfile.TemporaryDirectory() as directory:
      path = self.write_config(directory, {"model": {}, "mcp": {}})

      with patch("shikigen.app_config.DEFAULT_CONFIG_PATH", path):
        config = load_app_config()

    self.assertEqual(config.model.default, "deepseek-v4-flash")
    self.assertEqual(config.mcp.servers, {})

  def test_rejects_null_servers(self) -> None:
    with tempfile.TemporaryDirectory() as directory:
      path = self.write_config(
        directory,
        {"model": {}, "mcp": {"servers": None}},
      )

      with self.assertRaisesRegex(
        AppConfigError,
        r"(?s)servers.*(object|dictionary)",
      ):
        load_app_config(path)

  def test_reports_missing_file_with_path(self) -> None:
    path = Path("/definitely/missing/config.json")

    with self.assertRaisesRegex(AppConfigError, str(path)):
      load_app_config(path)

  def test_reports_invalid_json_location(self) -> None:
    with tempfile.TemporaryDirectory() as directory:
      path = Path(directory) / "config.json"
      path.write_text('{\n  "model":', encoding="utf-8")

      with self.assertRaisesRegex(AppConfigError, "Invalid config file"):
        load_app_config(path)

  def test_rejects_missing_and_unexpected_fields(self) -> None:
    with tempfile.TemporaryDirectory() as directory:
      missing_path = self.write_config(directory, {"model": {}})

      with self.assertRaisesRegex(AppConfigError, r"(?s)mcp.*Field required"):
        load_app_config(missing_path)

      unexpected_path = self.write_config(
        directory,
        {"model": {}, "mcp": {"servers": {}}, "unknown": True},
      )

      with self.assertRaisesRegex(AppConfigError, r"(?s)unknown.*Extra inputs"):
        load_app_config(unexpected_path)

  def test_rejects_invalid_field_types(self) -> None:
    with tempfile.TemporaryDirectory() as directory:
      path = self.write_config(
        directory,
        {"model": {"timeout": [30]}, "mcp": {"servers": []}},
      )

      with self.assertRaisesRegex(AppConfigError, "validation errors"):
        load_app_config(path)

  def test_rejects_unexpected_nested_mcp_fields(self) -> None:
    with tempfile.TemporaryDirectory() as directory:
      path = self.write_config(
        directory,
        {"model": {}, "mcp": {"servers": {}, "unknown": True}},
      )

      with self.assertRaisesRegex(AppConfigError, r"(?s)mcp.unknown.*Extra inputs"):
        load_app_config(path)

  def test_rejects_incomplete_server_configs(self) -> None:
    cases = [
      ({"transport": "http"}, "http", "url"),
      ({"transport": "stdio", "args": []}, "stdio", "command"),
    ]

    for server, transport, missing_field in cases:
      with self.subTest(server=server):
        with tempfile.TemporaryDirectory() as directory:
          path = self.write_config(
            directory,
            {"model": {}, "mcp": {"servers": {"example": server}}},
          )

          with self.assertRaisesRegex(
            AppConfigError,
            rf"(?s)example.{transport}.{missing_field}.*Field required",
          ):
            load_app_config(path)

  def test_rejects_unsupported_server_transport(self) -> None:
    with tempfile.TemporaryDirectory() as directory:
      path = self.write_config(
        directory,
        {
          "model": {},
          "mcp": {
            "servers": {
              "example": {"transport": "websocket", "url": "wss://example.com"}
            }
          },
        },
      )

      with self.assertRaisesRegex(AppConfigError, r"(?s)transport.*http.*stdio"):
        load_app_config(path)

  def test_rejects_unexpected_server_fields(self) -> None:
    with tempfile.TemporaryDirectory() as directory:
      path = self.write_config(
        directory,
        {
          "model": {},
          "mcp": {
            "servers": {
              "example": {
                "transport": "http",
                "url": "https://example.com/mcp",
                "unknown": True,
              }
            }
          },
        },
      )

      with self.assertRaisesRegex(AppConfigError, r"(?s)example.http.unknown.*Extra"):
        load_app_config(path)

  def test_resolves_environment_variables_recursively(self) -> None:
    with tempfile.TemporaryDirectory() as directory:
      path = self.write_config(
        directory,
        {
          "model": {},
          "mcp": {
            "servers": {
              "remote": {
                "transport": "http",
                "url": "https://example.com/mcp",
                "headers": {"Authorization": "$TEST_MCP_TOKEN"},
              },
              "local": {
                "transport": "stdio",
                "command": "uvx",
                "args": ["$TEST_MCP_PACKAGE"],
              },
            }
          },
        },
      )

      with patch.dict(
        "os.environ",
        {"TEST_MCP_TOKEN": "secret", "TEST_MCP_PACKAGE": "example-server"},
      ):
        config = load_app_config(path)

    remote = config.mcp.servers["remote"]
    local = config.mcp.servers["local"]
    assert isinstance(remote, HttpMcpServerConfig)
    assert isinstance(local, StdioMcpServerConfig)
    self.assertEqual(remote.headers, {"Authorization": "secret"})
    self.assertEqual(local.args, ["example-server"])

  def test_reports_missing_environment_variable_with_config_path(self) -> None:
    with tempfile.TemporaryDirectory() as directory:
      path = self.write_config(
        directory,
        {
          "model": {},
          "mcp": {
            "servers": {
              "github": {
                "transport": "http",
                "url": "https://example.com/mcp",
                "headers": {"Authorization": "$MISSING_MCP_TOKEN"},
              }
            }
          },
        },
      )

      with (
        patch.dict("os.environ", {}, clear=True),
        self.assertRaisesRegex(
          AppConfigError,
          r"mcp.servers.github.headers.Authorization.*MISSING_MCP_TOKEN",
        ),
      ):
        load_app_config(path)

  def test_leaves_non_placeholder_strings_unchanged(self) -> None:
    with tempfile.TemporaryDirectory() as directory:
      path = self.write_config(
        directory,
        {
          "model": {},
          "mcp": {
            "servers": {
              "example": {
                "transport": "http",
                "url": "https://example.com/mcp",
                "headers": {"Authorization": "Bearer $TEST_MCP_TOKEN"},
              }
            }
          },
        },
      )

      with patch.dict("os.environ", {"TEST_MCP_TOKEN": "secret"}):
        config = load_app_config(path)

    server = config.mcp.servers["example"]
    assert isinstance(server, HttpMcpServerConfig)
    self.assertEqual(
      server.headers,
      {"Authorization": "Bearer $TEST_MCP_TOKEN"},
    )
