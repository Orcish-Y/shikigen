# MCP Streamable HTTP 接入

2026-10-20，ticket 08。远程连接复用 stdio 的连接目录、发现预览、选中入库、统一 MCP 定义和执行入口。页面继续遵循 [工具原型](../../../frontend/design.md#工具页面原型)。

## 本次认证范围调整

用户确认“继续直接编辑和保存 headers，凭据隐藏机制留待统一设计”。因此本票不恢复 Credential，也不增加保留／替换／清空的特殊协议、已设置标志或已知密钥遮盖。headers 按字面保存，列表／详情直接返回实际值，页面原值回填；提交新的对象替换全部 headers，提交 `{}` 清空。密钥不进入业务 arguments，不展开环境引用，不写浏览器本地存储。此决定延续 [HTTP 认证记录](http-auth-credentials.md)，覆盖原票中的凭据隐藏与遮盖要求。

## 配置与公开操作

`tool_library.mcp_connections` 使用 `transport` 判别式联合保存 `McpStdioConnection` 或 `McpStreamableHttpConnection`，工具仍统一为 `McpToolDefinition(kind="mcp")`，通过 `(connection_id, remote_name)` 标识来源。既有 stdio 配置允许省略默认 transport；判别器在缺省时选择 stdio，保持原始输入和严格 JSON 校验，不让其他工具的保存因旧配置失效。

远程配置包含 `display_name`、`transport: streamable_http`、`url`、字符串对象 `headers`，以及独立的 `test_timeout_seconds`／`discovery_timeout_seconds`（默认 30 秒，范围 1–300）。URL 必须为 HTTP(S)，不能含用户名密码或片段；请求头拒绝非法名称、不可打印字符、大小写重复名称，以及 SDK 管理的协议头。配置校验不连接服务，暂时离线仍能保存。

`GET /api/mcp/schema/streamable_http` 提供专属管理 schema，stdio 继续使用 `/api/mcp/schema/stdio`。其余操作共用既有接口：

| 操作 | 接口 |
| --- | --- |
| 列表／详情 | `GET /api/mcp/connections`、`GET /api/mcp/connections/{id}` |
| 创建／更新 | `POST /api/mcp/connections`、`PUT /api/mcp/connections/{id}` |
| 初始化测试 | `POST /api/mcp/connections/{id}/test` |
| 工具发现 | `POST /api/mcp/connections/{id}/discover` |
| 选中入库 | `POST /api/mcp/connections/{id}/imports` |

创建返回 ID，更新返回 204，页面随后读取详情。更新保留 ID 和创建时间；连接类型不可在原连接上切换，接入另一种传输须新建连接。更新 URL／headers 不自动覆盖已入库来源结构。保存失败、保存成功但详情读取失败，以及保存结果不确定，继续沿用已有三种反馈。脏草稿不能测试旧配置，离开保留放弃确认。

## 会话与结果

`McpConnectionSessionProvider.open_mcp_session` 按 transport 获取独立会话。远程使用 MCP SDK 的 `streamable_http_client`，每次拥有自己的 HTTP client 和 MCP 会话，支持 JSON 及 SSE 响应。上下文退出终止本次远程会话并关闭本地 HTTP 连接；不使用跨操作会话池，也不自动重试业务调用。不自动跟随重定向。SSE 带事件 ID 时保留 SDK 的 Last-Event-ID 续读，无可恢复令牌而提前结束时立即返回传输错误。

测试只初始化；发现只初始化并分页读取目录，不调用业务工具。发现令牌、版本检查、整批校验和原子提交与 stdio 相同；再次选择同来源返回原 ID，保留本地信息及已保存来源快照。

执行仍由统一 `ToolExecutor` 控制总预算、输入校验和四种状态。连接、初始化、读取目录、调用和读取结果都在同一个执行预算内。超时／取消清理时，远端终止请求最多额外等待 0.5 秒；这是独立总截止，不是每次 I/O 空闲超时，持续慢速返回也不能拖住关闭。清理时间计入 duration_ms，不承诺撤销远端业务。原始结果、structuredContent、多块内容、附加字段与 `_meta` 沿用 [stdio 结果契约](mcp-stdio-tools.md)。目录最多 1000 项／1 MiB，业务返回最多 1 MiB。

诊断区分 `mcp_authentication`（HTTP 401／403）、`mcp_transport`（HTTP／连接错误）、`mcp_protocol`（协议异常）、`mcp_tool_error`（业务 isError）及 `mcp_output_validation`。HTTP 传输子任务失败引发 SDK 内部取消时，返回原始传输错误，不误报用户取消。HTML 或非法 JSON-RPC 响应通过 SDK 的公开 message_handler 传播解析错误，避免等到预算耗尽才误报超时。

页面只展示本页测试／发现事实，保存成功或一次成功不表示持续在线。工具参数仍来自已入库的动态 schema，调用结果使用共同的完整结果展示。

## 后续票据的共同边界

- 09：远程复用已有发现入口，补齐选择性来源更新、未发现项预览及连接删除；普通编辑不能改来源字段。
- 12：远程使用共同测试任务与后端生命周期取消，后续公开取消接口和离开交互直接适用，不另建远程任务系统。
- 13：调用准备时读取已保存连接快照，后续统一加强磁盘冲突和调用生效时点。

## 验证入口

`tests/test_mcp_http_api.py` 通过公开 API 和本地可控 HTTP 服务验证配置、认证、JSON／SSE 初始化、发现与真实调用、独立会话、完整结果、协议／传输／业务错误、预算、关闭清理及连接编辑。`tests/test_mcp_tool_api.py` 回归 stdio。`frontend/tests/mcp-management-dom.test.mjs` 验证远程专属动态表单和保存／重读／脏草稿行为；`frontend/src-tauri/tests/tool_library_acceptance.py` 提供真实桌面与窄屏验收。

独立的规范与规格审查及修复结果见 [实现审查](mcp-streamable-http.review.md)。

最终验证记录：

- 后端全量 427 项按四组隔离运行，1 项既有跳过，发现并修复 stdio 取消竞态；修复后远程／stdio 两个 API 文件共 19 项全部通过。旧配置缺 transport 的持久化回归也通过。
- 前端全量 374 项：373 项通过，1 项 Vite 启动测试超时；单独重跑该项通过。最终 MCP 页面 4 项交互测试通过。
- 真实桌面 2 项（远程与 stdio）通过，检查 1440px／390px 截图及窄屏滚动后的 headers 可见性，无页面横向溢出。
- 最终 TypeScript／Vite 构建、相关 Python 模块项目 ty／编辑器 ty、Ruff、格式与 diff 检查通过。

日志位于 `.scratch/tools-workflow/ticket08-*.log`，截图位于 `.scratch/tools-workflow/verification/native/test_mcp_http_form_discover_and_execute/`。没有在取消修复后再次运行不受影响的后端测试分组。

19 项回归日志曾出现一次 Windows Proactor ResourceWarning。随后对同一清理测试进行受控对比及重复验证，全部通过，观察到的传输均已进入关闭状态、无遗留 socket；未复现该警告，来源尚未确定。对比记录位于 `ticket08-cleanup-comparison.log`，未据此改变传输依赖或超时实现。
