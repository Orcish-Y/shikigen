import json
import os
import re
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

DEFAULT_CONFIG_PATH = Path("config.json")
_ENV_VAR_PATTERN = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)")


class AppConfigError(RuntimeError):
  """Raised when the application configuration cannot be loaded or validated."""


class ModelConfig(BaseModel):
  """Validated configuration for the application's chat model."""

  model_config = ConfigDict(extra="forbid")

  default: str = Field(default="deepseek-v4-flash", min_length=1)
  provider: str = Field(default="deepseek", min_length=1)
  base_url: str | None = Field(default=None, min_length=1)


class HttpMcpServerConfig(BaseModel):
  model_config = ConfigDict(extra="forbid")

  transport: Literal["http"]
  url: str = Field(min_length=1)
  headers: dict[str, str] | None = None
  timeout: float | None = Field(default=None, gt=0)
  sse_read_timeout: float | None = Field(default=None, gt=0)
  terminate_on_close: bool | None = None


class StdioMcpServerConfig(BaseModel):
  model_config = ConfigDict(extra="forbid")

  transport: Literal["stdio"]
  command: str = Field(min_length=1)
  args: list[str] = Field(default_factory=list)
  env: dict[str, str] | None = None
  cwd: str | None = None
  encoding: str | None = None
  encoding_error_handler: Literal["strict", "ignore", "replace"] | None = None


McpServerConfig = Annotated[
  HttpMcpServerConfig | StdioMcpServerConfig,
  Field(discriminator="transport"),
]


class McpConfig(BaseModel):
  model_config = ConfigDict(extra="forbid")

  initial_max_attempts: int = Field(default=3, ge=1)
  servers: dict[str, McpServerConfig] = Field(default_factory=dict)


class SubagentConfig(BaseModel):
  """工具名按 registry 中的实际名称匹配；None 继承，空列表禁用工具。"""

  model_config = ConfigDict(extra="forbid")

  tools: list[Annotated[str, Field(min_length=1)]] | None = None
  disallowed_tools: list[Annotated[str, Field(min_length=1)]] = Field(
    default_factory=list
  )


class SubagentsConfig(BaseModel):
  model_config = ConfigDict(extra="forbid")

  general: SubagentConfig = Field(default_factory=SubagentConfig)
  bash: SubagentConfig = Field(
    default_factory=lambda: SubagentConfig(
      tools=["bash", "read_file", "write_file", "list_dir", "grep"]
    )
  )


class CheckpointerConfig(BaseModel):
  """Checkpoint 后端；path 仅用于 sqlite，相对路径以工作目录为准。"""

  model_config = ConfigDict(extra="forbid")

  type: Literal["sqlite", "memory"] = "sqlite"
  path: str = Field(default=".shikigen/data/shikigen.db", min_length=1)


class DatabaseConfig(BaseModel):
  """应用聊天存储配置，相对路径以工作目录为准。"""

  model_config = ConfigDict(extra="forbid")

  path: str = Field(default=".shikigen/data/shikigen.db", min_length=1)


class AppConfig(BaseModel):
  model_config = ConfigDict(extra="forbid")

  model: ModelConfig
  mcp: McpConfig
  subagents: SubagentsConfig = Field(default_factory=SubagentsConfig)
  checkpointer: CheckpointerConfig = Field(default_factory=CheckpointerConfig)
  database: DatabaseConfig = Field(default_factory=DatabaseConfig)


def _resolve_env_vars(value: object, path: tuple[str | int, ...] = ()) -> object:
  if isinstance(value, dict):
    return {
      key: _resolve_env_vars(item, (*path, str(key))) for key, item in value.items()
    }
  if isinstance(value, list):
    return [_resolve_env_vars(item, (*path, index)) for index, item in enumerate(value)]
  if not isinstance(value, str):
    return value

  match = _ENV_VAR_PATTERN.fullmatch(value)
  if match is None:
    return value

  variable_name = match.group(1)
  if variable_name not in os.environ:
    location = ".".join(str(part) for part in path)
    raise AppConfigError(
      f'Config field "{location}" requires missing environment variable '
      f'"{variable_name}"'
    )
  return os.environ[variable_name]


def load_app_config(path: str | Path | None = None) -> AppConfig:
  """
  Load the application configuration from a file.

  Args:
      path (str | Path | None): The configuration file path. If None, use the
          project-root config file.

  Returns:
      AppConfig: The loaded application configuration.

  Raises:
      AppConfigError: If the file cannot be read or contains an invalid config.
  """
  config_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH

  try:
    content = config_path.read_text(encoding="utf-8")
    raw_config = json.loads(content)
    return AppConfig.model_validate(_resolve_env_vars(raw_config))
  except FileNotFoundError as exc:
    raise AppConfigError(f"Config file not found: {config_path}") from exc
  except json.JSONDecodeError as exc:
    raise AppConfigError(f"Invalid config file: {config_path}\n{exc}") from exc
  except ValidationError as exc:
    raise AppConfigError(f"Invalid config file: {config_path}\n{exc}") from exc
  except (OSError, UnicodeDecodeError) as exc:
    raise AppConfigError(f"Cannot read config file: {config_path}") from exc
