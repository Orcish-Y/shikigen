# MCP stdio 接入与选中工具调用

2026-10-20 补充：远程传输已接入同一连接集合和会话提供者，见 [Streamable HTTP 接入记录](mcp-streamable-http.md)。两种传输共用 `McpConnectionSessionProvider`；本记录中的 stdio 行为保持适用。

2026-10-18，ticket 07。服务连接、来源工具与本地工具定义分别保存。工具页和 MCP 服务页沿用 [demo 布局规则](../../../frontend/design.md#工具页面原型)。

## 范围与凭据前置条件

本次完成普通 stdio 连接、连接测试、发现预览、勾选入库和工具执行链路。遵循 2026-10-15 用户“删除 credential、后面统一设计”的决定，未恢复通用 Credential、隐藏读取、保留／替换／清空协议或已知凭据遮盖。环境变量目前是按字面保存和读取的字符串对象，不展开环境引用，也不声明为敏感字段。密钥仍不属于工具业务参数。

票据涉及敏感连接字段与遮盖的验收项尚未完成；它们依赖后续统一凭据设计。本次已向用户提出“先完成 MCP 主链路”与“本次统一设计凭据”两个选项，未将等待期间的无回复解释为凭据方案确认。现状依据见 [HTTP 认证记录](http-auth-credentials.md)。后续设计须同时明确 HTTP、MCP、OpenAPI 的存储、管理读取、编辑动作和日志／结果遮盖范围，不能直接恢复历史抽象。

## 连接管理

`tool_library.mcp_connections` 按稳定连接 ID 保存 `McpStdioConnection`，包含 `display_name`、`transport: stdio`、`command`、`args`、`env`、可选 `cwd`、`test_timeout_seconds` 和 `discovery_timeout_seconds`。两个操作预算均默认 30 秒，可调 1–300 秒。配置格式合法即可保存，不启动进程检查可达性。相对 cwd 以实际配置文件目录解释，未指定时沿用后端进程工作目录。

连接不覆盖顶层 `mcp.servers`，不自动挂载当前聊天 Agent。同一连接可供多个工具引用。连接 ID 与创建时间不随修改变化；配置版本是文件内容 SHA-256，更新必须提交读取版本。工具库其他分组和字面字符串保持原值。首版没有连接删除操作。

公开接口：

| 操作 | 接口 |
| --- | --- |
| 动态连接表单 | `GET /api/mcp/schema/stdio` |
| 列表／详情 | `GET /api/mcp/connections`、`GET /api/mcp/connections/{id}` |
| 创建／更新 | `POST /api/mcp/connections`、`PUT /api/mcp/connections/{id}` |
| 初始化测试 | `POST /api/mcp/connections/{id}/test` |
| 发现预览 | `POST /api/mcp/connections/{id}/discover` |
| 勾选入库 | `POST /api/mcp/connections/{id}/imports` |

创建返回 ID，更新返回 204；页面重读详情。保存成功但详情读取失败时锁定再次保存，只提供详情重读。没有收到保存响应时保留草稿并锁定重试，允许明确放弃草稿后重读列表。连接未保存或有修改时不能测试旧配置。状态展示是本页实际观察，不由保存成功或工具启用推断在线。

## 发现和入库

测试只初始化，不调用 `tools/list` 或业务工具。发现只初始化并分页读取 `tools/list`，不调用业务工具；最多 1000 项、1 MiB，重复远端名称／分页游标明确失败。来源字段按 SDK 原始模型以别名输出，保留工具的附加事实。

发现成功产生后端内存 `discovery_id`，关联真实来源、连接 ID、配置版本，10 分钟过期，最多保留 100 批。入库只提交该 ID 和所选 `{remote_name, name}`；后端从缓存取回发现版本与来源 schema，并检查当前配置版本是否仍匹配。客户端不能提交伪造的来源 schema 或绕过权限标志。配置变化、跨连接使用、过期和不在发现中的工具均拒绝。

前端使用已有工具与 `reserved_names` 建议本地调用名称，同名来源自动加后缀；用户可改新项名称。后端执行与普通保存相同的名称、schema 校验。整批准备完成后原子提交，任一项无效不会保存部分结果。未选择的来源不入库。

新 MCP 定义保存 `connection_id`、`remote_name`、完整 `input_schema`／`output_schema` 和完整 `source_tool`。对同一 `(connection_id, remote_name)` 再次入库返回原 ID，保留所有本地信息和原来源快照。普通创建／无原项的草稿测试不能伪造 MCP 定义；普通编辑及已存在工具的草稿测试仅允许本地页面名称、调用名称、说明、启用和超时，保护来源身份、schema 和完整来源。对应 [普通编辑与发现更新规则](tool-edit-drafts.md#mcp-普通编辑与发现更新的接入规则)。

09 应从独立发现入口继续加入来源差异预览、确认更新、消失处理和本地编辑保留策略。不要逐项调用普通 `save_tool`，也不要增加客户端可控的权限绕过标志；需延续真实来源校对、版本检查和整批提交。

## 会话与执行结果

运行装配登记 `mcp -> McpAdapter`。工具库准备含定义与连接快照的 `McpToolExecution`，适配器不读取持久配置。`McpSessionProvider.open_mcp_session` 负责会话获取与释放，当前实现每次测试、发现、调用都创建独立 stdio 进程／会话，不实现会话池、不保证跨调用进程状态。

调用进入共用 `ToolExecutor` 的严格输入校验和工具总预算；原 `inputs` 直接作为远端 `arguments`。调用会话初始化后读取当前来源，用它校验来源输出。stdio SDK 负责关闭 stdin、等待和必要的进程树终止，Windows 进程使用隐藏窗口。提供者在会话退出前保留原操作异常，资源释放完成后再传播，避免 SDK 清理异常覆盖取消原因。stderr 调试流不混入业务结果或应用日志。

使用 SDK 的公开低层 `send_request` 获取 `CallToolResult`，保留原始返回后再执行与 SDK 同等的 `outputSchema` 校验。`ClientSession.call_tool` 在输出校验异常时会丢失对原始结果的访问，因此这里不采用该便捷方法。详情见 [Python SDK v1.29.0](https://github.com/modelcontextprotocol/python-sdk/tree/v1.29.0) 与 [MCP 工具协议](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)。项目直接声明 `mcp>=1.29.0,<2` 依赖。

`data` 优先 `structuredContent`，未提供或显式 null 时为完整内容块数组，空对象仍作为结构化数据。`details` 包含来源 ID、远端名称、当前 `source_tool` 及 `raw_result`，保留 `_meta`、多内容块和扩展事实。`isError` 返回 `mcp_tool_error`；来源输出不合法／缺少结构化返回是 `mcp_output_validation`；协议／SDK 异常是 `mcp_protocol`；工具不存在是 `mcp_tool_missing`。失败不包装成成功。当前来源输出使用 `referencing.Registry()`，只解析已提供 schema 内的引用，不额外拉取外部地址；无法解析的引用明确失败并保留原返回。

原始业务返回最多 1 MiB，超过时明确返回 `output_limit` 和实际字节数，省略完整值，不悄悄截断伪装完整成功。超时／关闭取消延续统一 `timeout`／`cancelled` 状态，并回收本次持有进程。

## 验证

公开 API 与真实 stdio 对端：`tests/test_mcp_tool_api.py`、`tests/fixtures/mcp_stdio_server.py`。页面交互：`frontend/tests/mcp-management-dom.test.mjs` 与现有工具页 DOM 测试。Windows WebView：`tool_library_acceptance.test_mcp_stdio_discover_select_call_and_source_navigation`，检查 MCP 服务与工具页跳转、真实参数／完整返回及 1440px／390px 布局。

后端全量 416 项通过（1 项跳过，`.scratch/tools-workflow/ticket07-backend-full.log`）。全量执行期间补查发现实时来源输出的外部引用默认拉取和 SDK 取消清理覆盖异常，随后修正；最终 MCP 专项 9 项通过（`ticket07-mcp-api-final.log`，含新增外部引用回归及显式 null 回退），取消／超时与进程退出用例再重复 5 轮全部通过（`ticket07-cancel-repeat.log`）。成功、初始化超时、调用超时和关闭取消后均实际检查所持进程已退出。

前端全量 373 项通过（`ticket07-frontend-full.log`），包括 MCP 服务页 3 项和工具页 38 项 DOM 交互。TypeScript／Vite 构建通过（`ticket07-build-final.log`）。Windows WebView 新 MCP 流程及现有 HTTP 创建／重读／主题／聊天导航共 2 项通过（`ticket07-native-final.log`）；1440px／390px 服务页与工具页截图已实际查看，无页面横向溢出，窄屏三个服务操作均可见。截图在 `.scratch/tools-workflow/verification/native/test_mcp_stdio_discover_select_call_and_source_navigation/`。

修改的 Python 后端与测试通过 Ruff、格式检查和 ty。全库 ty 仍报告原有 263 项诊断，均未命中本次修改文件（`ticket07-ty-full.log`），不声明全库类型检查通过。

## Standards

固定基点 `474597fd00b5b3f0a57a9171ff073690247fe22b`，规范与需求分别由独立审查执行。规范最终 0 项违规、0 项未解决建议。初审建议合并的 MCP 来源字段清单已提取为 `MCP_SOURCE_FIELDS`，保存拒绝的共享判定也已收敛到 `tool-save-errors.ts`。新增输出引用限制、取消异常保留逻辑均已复核。

## Spec

1 项已知部分完成：票据的敏感字段编辑协议与已知凭据遮盖，受此前移除 Credential、等待统一设计的用户决定约束，仍是待确认范围。其余需求审查未发现新增未解决缺陷或范围扩张。后续外部引用限制、取消清理保留原异常及 null／空对象回退语义已复核，并有公开 API／真实进程回归佐证。不得将此票标记为全部验收完成。
