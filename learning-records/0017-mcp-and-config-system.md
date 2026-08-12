# MCP 集成 + Pydantic 配置系统

用户实现了完整的配置驱动架构，项目从 "代码硬编码" 升级到 "JSON 配置驱动"。

**配置系统** (`harness/app_config.py`):
- Pydantic `extra="forbid"` 严格校验
- `McpServerConfig` discriminated union on `transport`（http vs stdio）
- `_resolve_env_vars()` 递归解析 `$ENV_VAR` 模式，安全注入环境变量
- `load_app_config()` 读 JSON → 解析 env → 校验 → 返回类型安全的 AppConfig

**MCP 加载器** (`tools/mcp_loader.py`):
- `load_mcp_tools(config)` — Pydantic model → MultiServerMCPClient，并行加载所有 server
- per-server 独立 retry（`_load_server_tools`），一个 server 失败不影响其他

**模型工厂** (`harness/model.py`):
- `create_chat_model(config)` — 从配置创建 ChatModel

**main.py 启动序列**：`load_config → create_model → create_registry → load_mcp_tools → register → create_agent`

**安全问题**：初版含明文 GitHub PAT，已改为 `$GITHUB_TOKEN` 环境变量引用。

**Evidence**: `harness/app_config.py` (121 行), `tools/mcp_loader.py` (74 行), `harness/model.py` (13 行), `config.json`

**Implications**: 项目接近 deer-flow 的 harness/app 分层。配置驱动的模型选型 + 工具加载 + MCP 集成就绪，无需为新能力写 Python 代码。
