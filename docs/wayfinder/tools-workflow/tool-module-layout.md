# 工具模块布局

2026-10-21 用户确认：将工具能力集中在 `tools/`，内置工具单独存放，其余按 HTTP、Python、MCP 类型组织。后续工具票据沿用此布局。

```text
tools/
├── builtin/                 # add、filesystem、time、web 等 Agent 内置工具
├── http/
│   ├── execution.py         # HTTP 请求执行
│   └── openapi_import.py    # OpenAPI 解析、预览和 HTTP 定义转换
├── python/
│   ├── execution.py         # Python 工具执行
│   └── worker.py            # 子进程入口
├── mcp/
│   ├── execution.py         # MCP 工具调用
│   ├── sessions.py          # MCP 连接会话
│   └── http_transport.py    # MCP HTTP 传输
└── executor.py              # 统一校验、超时预算和按 kind 分发
```

OpenAPI 是 HTTP 工具的创建入口，生成既有 `HttpToolDefinition`，不新增运行类型。MCP 的发现和入库仍由 `runtime/tool_library.py` 协调，协议调用、会话及传输放在 `tools/mcp/`。

`core` 继续负责工具注册和 Agent 组装；`contracts` 负责工具定义与执行契约；`persistence` 负责配置和源码存取；`runtime/tool_library.py` 负责管理、发现／导入协调及保存。工具执行器和适配器不反向依赖 runtime。

调用方直接使用新模块路径：内置工具从 `shikigen.tools.builtin` 或其具体模块导入。`tools/__init__.py` 只说明包职责，不汇总导出内置工具或执行器。迁移后移除原执行／导入包及旧内置工具路径，不保留兼容别名。Python 适配器通过同目录 `worker.py` 启动子进程。

迁移验证使用既有包导入、内置工具、执行器、HTTP／Python／MCP／OpenAPI 公开接口、Agent 组装及生命周期测试，覆盖安装后在项目外导入和真实 Python 子进程执行。首轮 122 项中 121 项通过，另有子 Agent 测试 7 项通过；首次失败的 MCP 取消用例调整后，所属 HTTP 文件 11 项全部通过，合计验证 129 项相关回归。

该 MCP 用例原本在取消阶段沿用上一阶段的 1 秒超时预算，且在本地清理返回后立即断言远端线程已清空会话。现为取消阶段恢复独立预算，并有界等待远端清理，保留请求超时、关闭耗时、取消结果和会话清理断言；生产逻辑未改动。日志为 `.scratch/tools-workflow/tool-layout-tests.log`、`tool-layout-task-tests.log` 和 `tool-layout-mcp-tests-final.log`。

Ruff、格式检查、源码 ty 和变更文档的工具链接检查通过。逐文件比较确认 12 个迁移的已跟踪模块除导入路径及 worker 文件名外与原内容相同；新进程检查确认原模块路径不存在，没有兼容导出。
