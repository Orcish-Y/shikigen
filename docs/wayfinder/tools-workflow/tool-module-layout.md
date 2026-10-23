# 工具模块布局

2026-10-21 用户确认：将工具能力集中在 `tools/`，内置工具单独存放，其余按 HTTP、Python、MCP 类型组织。后续工具票据沿用此布局。

2026-10-23 补充：按是否依赖 Agent／Run 上下文划分职责。工具库管理、跨线程调用和同步脚本入口统一归 `tools/`；需要 Agent／Run 上下文的调用协调归运行层，形成独立模块时可放入 `runtime/tool/`。

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
├── executor.py              # 统一校验、超时预算和按 kind 分发
├── tool_instance.py         # LangChain 工具实例，同步／异步入口与完整结果封装
├── tool_library.py          # 同步／异步入口、配置管理、发现／导入和手工测试
└── tool_calls.py            # 工具库所属循环、同步与跨循环调用桥接
```

OpenAPI 是 HTTP 工具的创建入口，生成既有 `HttpToolDefinition`，不新增运行类型。MCP 的发现和入库仍由 `tools/tool_library.py` 协调，协议调用、会话及传输放在 `tools/mcp/`。

`core` 负责工具注册和 Agent 组装；`contracts` 负责工具定义与执行契约；`persistence` 负责配置和源码存取；`tools/tool_library.py` 负责管理、发现／导入协调及保存。`runtime/composition.py` 注入工具库并衔接应用关闭。工具包不反向依赖 runtime。

工具库的同步／异步入口集中在 `tools/tool_library.py`：异步宿主使用 `ToolLibrary`，同步脚本使用 `open_sync_tool_library()` 管理后台循环及资源关闭。循环归属与跨线程转交仍由 `tools/tool_calls.py` 实现。`ToolInstance` 通过注入的同步／异步执行函数调用工具库，不依赖 runtime；各类型适配器继续共享同一条执行链路。用法与关闭约束见[同步调用](stable-id-consumer-reuse.md#同步调用)。

`ToolCallBridge` 服务于工具库的锁与执行循环，`open_sync_tool_library()` 可由普通脚本直接使用，两者均不读取 Agent／Run／对话上下文。工具执行的超时、取消和资源清理同样属于工具自身能力。Agent 的审批、调用事件及 Run 取消与工具调用的衔接属于运行协调，不能仅因为代码使用异步任务，就把工具自身能力放回 runtime。

调用方直接使用新模块路径：内置工具从 `shikigen.tools.builtin` 或其具体模块导入。`tools/__init__.py` 只说明包职责，不汇总导出内置工具或执行器。迁移后移除原执行／导入包及旧内置工具路径，不保留兼容别名。Python 适配器通过同目录 `worker.py` 启动子进程。

迁移验证使用既有包导入、内置工具、执行器、HTTP／Python／MCP／OpenAPI 公开接口、Agent 组装及生命周期测试，覆盖安装后在项目外导入和真实 Python 子进程执行。首轮 122 项中 121 项通过，另有子 Agent 测试 7 项通过；首次失败的 MCP 取消用例调整后，所属 HTTP 文件 11 项全部通过，合计验证 129 项相关回归。

该 MCP 用例原本在取消阶段沿用上一阶段的 1 秒超时预算，且在本地清理返回后立即断言远端线程已清空会话。现为取消阶段恢复独立预算，并有界等待远端清理，保留请求超时、关闭耗时、取消结果和会话清理断言；生产逻辑未改动。日志为 `.scratch/tools-workflow/tool-layout-tests.log`、`tool-layout-task-tests.log` 和 `tool-layout-mcp-tests-final.log`。

Ruff、格式检查、源码 ty 和变更文档的工具链接检查通过。逐文件比较确认 12 个迁移的已跟踪模块除导入路径及 worker 文件名外与原内容相同；新进程检查确认原模块路径不存在，没有兼容导出。

2026-10-23 工具库与同步入口补充迁移验证：工具管理、同步调用、HTTP／Python／MCP／OpenAPI、工具注册与 Agent 组装等相关用例共 184 项通过。首轮 165 项中 164 项通过，运行环境测试文件因启动命令未加入同目录 fixture 路径而未加载；使用项目的 `discover` 方式补跑该文件，20 项通过。全部后端源码 ty、修改文件的 Ruff／格式检查通过；项目目录外可导入三个新模块，旧模块路径已移除。日志位于 `.scratch/tools-workflow/tool-package-migration-tests.log` 和 `tool-package-migration-runtime-tests.log`。
