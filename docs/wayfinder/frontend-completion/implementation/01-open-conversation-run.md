# 打开会话并核实运行状态

Status: done

实施进度：已验收（2026-10-04）

来源：[统一实施规格](../../../../.scratch/frontend-completion/PRD.md)；[公共要求与依赖总览](index.md)。

**What to build:** 从工作台新建或打开会话，读取完整历史，确认当前／最近运行身份和中文状态；重新进入工作台后已有记录和输入仍可继续使用。

**Why:** 先建立查询和会话数据归属，让后续操作有可信目标；将必要的数据所有者整理放进这条可演示的读取路径。

**API／边界：**既有创建会话、历史查询与宿主状态；历史外层 run_status；新增纯读 RunSnapshot 查询；BackendSession 地址租约和选择代次。

**Blocked by:** 无，可立即开始。

## 验收条件

- [x] 历史保留完整公开记录并按 seq 排序，每条外层 run_status 来自所属 Run 查询时状态，同 Run 在一次响应中一致；空历史、读取中和读取失败分开。
- [x] 末条消息定位 run_id／run_status，快照 id 与 SSE run_id 在边界统一并核对 thread_id；未开始、运行中、等待审批、已完成、已取消、运行失败使用中文，未知不能当未开始。
- [x] Run 快照只读已提交事实，no-store，不调用会写入恢复错误的旧 interrupted 校验路径；归属错误 404、暂不可读 503／Retry-After、损坏 500 不改变 Run。
- [x] 会话事实、选择和内存输入归属不随 Workspace 卸载；宿主租约撤销和旧选择的迟到响应不能写入新目标，既有正常发送和观察路径保持可用。
- [x] 新建返回有效 thread_id 且用户意图仍当前时选中，否则保留条目并提示；结果未知只读列表核对，不自动再建；已创建后的列表失败不撤销创建。
- [x] 没有会话时不把草稿存到空 ID；当前有服务端 title 时使用它，否则先显示新会话，完整 ID 保留可查。
- [x] 通过公开 HTTP／Runtime 查询验证纯读与身份，在当前 Tauri 工作台演示新建、打开、终态读取及宿主非 ready 后恢复记录。

## Comments

### 2026-10-04 实施记录

- 后端：历史通过单条 JOIN 返回完整消息及查询时 `run_status`；新增 `Runtime.runs.get_run_snapshot()` 与 `GET /api/threads/{thread_id}/runs/{run_id}`，只读已提交事实。历史与快照统一 `no-store`；404、503／Retry-After: 1、500 不改变 Run。
- 前端：新增应用持有的 `ConversationStore`，由 App 订阅，Workspace 卸载和 BackendSession 换代保留选择、记录及内存草稿。所有请求绑定租约与选择的取消信号，消息和快照核实身份；终态使用 JSON 快照，运行中／等待审批沿用 GET SSE。
- 界面：复用现有徽标、提示和详情样式，运行状态使用中文；读取中、失败与真实空历史分开。服务端标题优先，否则显示“新会话”；工具栏、会话项提示及详情可查完整会话 ID，无会话时禁用草稿输入。
- 新建：先保留有效创建结果，再读取列表；迟到结果不改变新的选择。结果未知时只 GET 列表核对，后续列表失败不撤销创建。

### 审查

以开始时干净的 `2ce5a8298dab46f59d148e4b2ab175c8724aff9f` 为基准，按 code-review 分别进行 Standards 与 Spec 只读审查，并复核修复。

- Standards：无文档硬标准违规。发现新 Run metadata 继承上一轮错误／用量／结束时间的问题；已按 Run 身份隔离，回归先失败、修复后通过，复核无待修项。
- Spec：发现 SSE 回放同 seq 消息时丢失已加载历史外层字段的问题；已保留完整原记录并合并正文，回归先失败、修复后通过，复核无待修项。

### 验证

- [HTTP／Runtime 专项](../../../../tests/test_conversation_queries.py)：3 项通过，覆盖完整历史、各 Run 状态、暂停快照纯读、身份归属、暂不可读与损坏时事实不变。
- [客户端边界](../../../../frontend/tests/backend-client.test.mjs)、[会话状态](../../../../frontend/tests/conversation-state.test.mjs)与既有宿主状态测试：前端全量 17 项通过。覆盖租约更换、迟到选择、创建失败／未知结果、正常发送、完整回放记录及新 Run 字段隔离。
- [真实 Tauri 验收](../../../../frontend/src-tauri/tests/client_acceptance.py)：4 项全部通过；使用隔离临时项目／数据库和确定性 Agent，实际 Windows 宿主及 WebView。验证新建、历史与终态读取、正常发送、审批后观察、旧请求隔离，以及宿主从 45200 换到 45201 后记录／草稿保留且不重发。
- Tauri 证据：[验收产物目录](../../../../.scratch/frontend-completion/ticket-01-native/)、[恢复后的窗口内容截图](../../../../.scratch/frontend-completion/ticket-01-native/test_running_sse_survives_page_reload_and_recovers_on_new_port_without_resend/window.png)。截图来自原生窗口内 WebView；已查看并核对现有工作台样式。
- Python 全量：276 项，275 通过、1 项按环境跳过、无失败（312.123 秒）；[完整日志](../../../../.scratch/frontend-completion/ticket-01-python-tests.log)。命令为 `.venv/Scripts/python.exe -X utf8 -m unittest discover -s tests -v`。
- `tsc --noEmit`、`ty check app packages/harness`、本票变更的 Python 文件 `ruff check`、Vite 生产构建、`git diff --check` 与票据本地链接核对均通过。沙箱下检查较慢；自动审批曾因额度不足拒绝执行一次构建，用户要求继续后已重新执行成功。

本票保留草稿至本次应用关闭；跨应用重启持久化与完整发送确认由第 4 票继续实施。仅第 1 票进入本轮实现，未修改 Git 暂存或创建提交。
