# MCP 重新发现与连接生命周期

2026-10-20，ticket 09。沿用[工具页面原型与参照规则](../../../frontend/design.md#工具页面原型)、[普通编辑与发现更新规则](tool-edit-drafts.md#mcp-普通编辑与发现更新的接入规则)及 [MCP 接入](mcp-stdio-tools.md)。stdio 与 Streamable HTTP 使用同一发现和提交逻辑。

## 发现预览与应用

`POST /api/mcp/connections/{id}/discover` 从同一次配置读取取得连接、工具库与内容版本，再建立独立 MCP 会话读取真实来源。它不执行业务工具，也不写配置。成功响应在原始 `tools` 之外增加 `changes`：

| status | 含义 | 页面操作 |
| --- | --- | --- |
| `new` | 尚未入库的来源 | 可勾选添加，并填写本地调用名称 |
| `changed` | 同连接、远端名称对应的完整来源发生变化 | 可对照已保存／本次来源结构，勾选应用 |
| `unchanged` | 来源与已保存快照相同 | 展示，不重复应用 |
| `missing` | 本次成功发现未返回某个已入库来源 | 展示“本次未发现”，保留定义及启用状态 |

每项带 `remote_name`、`tool_id`、`local_name`、`source_tool` 与 `previous_source_tool`。完整来源比较包括输入／输出 schema 和其他来源事实。本次失败只返回实际错误，没有可应用的发现凭证，不用空发现覆盖保存结构；成功但工具列表为空则明确列出全部未发现项。远端改名是新来源，不推测它对应哪个旧工具。

页面仅将勾选项交给现有独立入口 `POST /api/mcp/connections/{id}/imports`，请求为 `{discovery_id, tools: [{remote_name, name}]}`。后端从真实发现快照取结构，检查凭证所属连接、有效期和整个配置的 SHA-256 读取版本；客户端不提交来源结构或权限绕过标志。以 `(connection_id, remote_name)` 匹配来源，一项来源最多一项定义。同来源更新保留 ID、创建时间、页面名称、调用名称、说明、启用与超时，只替换所选来源的 `source_tool` 和输入／输出 schema；不同连接／远端名创建新身份。

普通保存与草稿测试仍调用 `_check_tool_edit_permissions`，拒绝改写所属连接、远端身份及来源 schema／完整来源；发现应用在核对凭证后直接复用 `_prepare_tool`，不走普通保存。所有所选定义逐项验证通过后，复用 `_commit` 一次写入；名称冲突、无效 schema 和版本冲突都不部分保存，定义诊断包含对应远端名称。无来源变化的既有项不写入。完整跨进程磁盘并发强化仍由 13 负责。

## 连接编辑与删除

连接命令、地址、headers 等显式保存后保留连接 ID，不改变已入库 schema；页面提示重新发现核对结构。有修改时禁止测试旧配置，离开支持保存并离开、放弃和继续编辑。保存失败保留草稿，保存成功但详情读取失败只允许重读／直接离开；响应丢失则保留“不确定”状态，不自动重复提交。

服务页列出实际所属工具并可跳转。删除先重读工具库，展示旗下工具名称、数量及影响；用户确认后发送 `DELETE /api/mcp/connections/{id}`，请求 `{version}`。后端核对读取版本，在单次配置提交中移除连接和所有所属工具，成功返回 204。版本变化要求重新核对影响；响应丢失提示结果不确定并提供重读，成功后重读失败明确标注已删除。其他连接与工具不受影响，不留下本次删除连接的孤立定义。

删除影响未来按 ID 发起的调用，它们明确报 `not_found`。已经开始的调用持有定义与连接快照，继续执行；删除不会关闭其会话。没有删除回滚／回收站。

凭据沿用用户在 04／08 的决定：认证保留，headers／env 直接编辑保存回填；通用 credential 与隐藏机制留待统一设计。本票不重新引入遮盖协议。

## 验证入口

- `tests/test_mcp_tool_api.py`：真实本地 stdio 服务，公开 API 验证选择性更新、ID／本地编辑保留、普通编辑与草稿测试越权拒绝、整批失败、发现失败／未发现保留、跨连接身份及级联删除期间已开始调用继续完成。
- `tests/test_mcp_http_api.py`：本机 HTTP MCP 服务验证同一生命周期；headers 修改不自动改变来源，重新发现后才应用所选来源。
- `frontend/tests/mcp-management-dom.test.mjs`：预览与勾选、所属工具跳转、删除影响与取消、脏草稿保存失败和保存并离开，延续保存响应／详情读取失败的恢复回归。
- `frontend/src-tauri/tests/tool_library_acceptance.py`：真实 Windows WebView 验证连接脏草稿、结构变化与未发现预览、选择性更新及删除确认；1440px／390px 截图在 `.scratch/tools-workflow/verification/native/test_mcp_stdio_discover_select_call_and_source_navigation/`，已实际查看并核对横向溢出。

验证记录：前端最终全量 378 项全部通过（`09-frontend-full-final.log`）；首次全量的既有 Vite 端口用例超时，单文件 9 项复测及最终全量均通过，没有调整超时或产品代码。MCP 页面最终 8 项通过（`09-ui-final.log`）。TypeScript／Vite 生产构建通过（`09-build-final.log`），Python 修改文件的 Ruff／格式检查及全部后端源码 ty 通过。真实 Windows WebView 的 stdio 生命周期流程通过（`09-native.log`）。日志均在 `.scratch/tools-workflow/`。

后端最终全量 431 项，430 项通过、1 项跳过（`09-backend-full-final.log`）。首次全量发现上次模块拆分遗留的生命周期测试 mock 路径错误，修正到 `core.tool_assembly.load_mcp_tools` 后，生命周期专项 3 项及最终全量均通过。两路[实现审查](mcp-discovery-lifecycle.review.md)均为 0 项遗留。
