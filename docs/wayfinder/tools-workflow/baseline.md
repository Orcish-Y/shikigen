# 工具模块现状调查

调查日期：2026-10-12。仅阅读仓库，未执行产品测试，未读取实际配置或密钥。

| 范围 | 已有基础与缺口 | 代码入口 |
| --- | --- | --- |
| 可调用集合 | `ToolRegistry` 保存 BaseTool，按 name 去重，同名后注册者被忽略；没有持久工具身份 | [tool_registry.py](../../../packages/harness/shikigen/core/tool_registry.py) |
| MCP | 配置服务连接，支持 stdio / http；按服务发现多个 BaseTool，添加服务名前缀，单服务发现失败隔离 | [app_config.py](../../../packages/harness/shikigen/app_config.py)、[mcp_loader.py](../../../packages/harness/shikigen/core/mcp_loader.py) |
| HTTP | 已有网页抓取与搜索，但服务实现写死；没有用户定义 method / URL / headers / query / body 的通用工具 | [web_fetch.py](../../../packages/harness/shikigen/tools/builtin/web_fetch.py)、[web_search_client.py](../../../packages/harness/shikigen/tools/builtin/web_search_client.py) |
| 代码 | Python >=3.12；已有 shell 工具，但没有用户录入 Python 片段的工具或执行适配器 | [harness 依赖](../../../packages/harness/pyproject.toml)、[filesystem.py](../../../packages/harness/shikigen/tools/builtin/filesystem.py) |
| Agent 装配 | 启动时建立 Registry、发现 MCP、创建 Agent；可注入主/子 Agent 的 Registry，尚无工具更新服务 | [composition.py](../../../packages/harness/shikigen/runtime/composition.py)、[agent.py](../../../packages/harness/shikigen/core/agent.py) |
| 审批 | 目前显式覆盖 write_file 与 bash；新工具不会自动继承这两项策略 | [approval.py](../../../packages/harness/shikigen/core/approval.py) |
| 页面与 API | “工具与技能编排”只有禁用导航；无 tools / workflow / custom-agent CRUD 路由 | [Sidebar.tsx](../../../frontend/src/components/Sidebar.tsx)、[server.py](../../../app/server.py) |
| 持久化 | SQLite 已有会话与运行存储，没有工具定义、MCP 连接或工具引用表 | [schema.py](../../../packages/harness/shikigen/persistence/schema.py) |
| 聊天记录 | ToolRecord / MessageContent 表示某次调用结果，不能充当可复用定义 | [tool-records.ts](../../../frontend/src/tool-records.ts)、[backend-client.ts](../../../frontend/src/backend-client.ts) |
| 凭据 | 当前配置支持整个字符串 `$ENV_NAME` 解析，不支持 `Bearer $ENV_NAME` 的内嵌替换 | [app_config.py](../../../packages/harness/shikigen/app_config.py) |

可复用接缝的代码结构推断：各类配置经过适配器转换成 `BaseTool`，再交给已有 `ToolRegistry` 与 Agent 装配。MCP 的连接配置与发现出的单个工具需要分别表达；具体持久模型、适配器接口和生效规则尚待决策。

