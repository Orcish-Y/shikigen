# 首版 Tauri 聊天工作台实施票据

Status: ready-for-agent

补齐首版真实聊天、运行恢复、审批／取消、中止正文保存、完整内容与资源、详情和导航；来源：[统一实施规格](../../../../.scratch/frontend-completion/PRD.md)。

发布日期：2026-10-04。用户已确认 23 张票据的粒度、直接阻塞依赖及拆分安排，答复“按方案定稿并发布（推荐）”。共 156 条验收条件；第 1–14 票已实现并完成各票核心验收，其余票据待实施。完整仓库回归的未解决问题另行记录，不能将票据完成等同于所有仓库测试通过。

文件组织：2026-10-04 按用户提出的目录与粒度要求，每张实施票据独立保存于本目录。本索引汇总公共要求与直接依赖；原有 [Wayfinder 地图](../map.md)及 tickets/ 记录规划决策。

工作 frontier：阻塞票全部完成的票即可开始，每次推进一票；以下按依赖顺序编排，独立分支可自行安排。2026-10-06 第 1–14 票已完成；本轮收尾：**第 14 票“自动预览工作目录内的本地图片”**（固定工作目录资源身份、纯 GET 解析／图片、受控 Blob 预览与详情、局部重试、租约清理及段落阅读锚点）。显式 `gpt-6-luna / max` 执行完整后端 **329 项：328 通过、0 失败／错误、1 Windows symlink 权限跳过**；最后等价命名／未使用字段调整后 HTTP8、后端 Ruff／ty 通过，未重复完整后端。App 租约详情逻辑修复后完整前端 **172 通过**；最后纯局部变量改名后 TypeScript、构建和原生定向 **1 通过**。原生首批 **7 项：4 通过、1 失败、2 错误**，夹具修正后图片三项 **3 通过**；租约详情红灯 **1 失败**保留，修复后最终绿灯通过。分批 **8 个唯一原生用例**各有通过证据，不声称一次 8／8 全绿；新租约用例模拟公开 Tauri 桥状态帧，不代表实际 BackendManager 重启。Standards／Spec 无剩余硬问题；主 agent 核对七条验收证据并关闭本票，完整过程、命令、截图与覆盖边界见[第 14 票报告](../../../../.scratch/frontend-completion/ticket-14/report.md)。Vite 主 chunk 583.20 kB 提示保留。本轮未执行任何 Git 命令。下一票：**第 15 票“每次确认后用系统程序打开工作目录文件”**，本轮未开始。

第 13 票历史结果保留：完整审批输入及捕获提交跨重启保存、全量 GET 核实、未知结果人工继续、404 只读保留、按完整身份清理。显式 `gpt-6-luna / max` 执行唯一完整前端回归 **164 通过**，之后身份清理修复及新增测试的最终受影响专项 **91 通过**（含全部 13 项恢复测试）；分批 **7 个唯一真实 Tauri 用例各有最终通过证据**，真实 HTTP／SQLite／Graph 专项 **1 通过**。TypeScript、最终构建及 **6 个 Python 文件** Ruff 通过；预置 5173 服务与当前 dist 全部 **38 文件**字节一致。原生早期失败批次和夹具修复保留，不改算通过，不声称最终重跑前端全套或一次原生 7／7 全绿。Standards／Spec 无剩余硬问题；本票无后端产品、Rust、依赖或 API 变更，未重复完整后端回归。主 agent 已核对日志、请求、结果与截图，完整证据及七条验收对应见[第 13 票报告](../../../../.scratch/frontend-completion/ticket-13/report.md)。当轮用户明确禁止 Git 修改；未暂存、未提交、未切换分支。

第 12 票历史结果保留：真实请求按原顺序逐项批准／拒绝、完整只读参数、同 Run 提交、metadata 接受与互斥、真实审批处理记录及历史详情。显式 `gpt-6-luna / max` 完成最终 Node **152 通过**、唯一完整后端回归 **321 项：320 通过、0 失败／错误、1 Windows 符号链接权限跳过**，最终 HTTP 专项 **1 通过**；真实 Tauri 首轮 **12 项：0 通过、2 失败、10 错误**均止于环境连接，实机隔离首例 **1 通过**、其余 **11 项：9 通过、2 失败**，修复后最终定向 **7 通过、0 失败／错误／跳过**，分批共覆盖 12 个唯一原生用例，历史失败不改算通过。TypeScript／构建／产品 ty／新增三文件 Ruff 通过；新增 Graph 测试 ty 保留 **2 条 TypedDictLike 兼容诊断**，不算通过，官方状态类型可复现。Standards／Spec 无剩余硬问题；本票无后端产品或 Rust 改动。完整命令、八条验收对应证据、日志、截图与范围见[第 12 票报告](../../../../.scratch/frontend-completion/ticket-12/report.md)。

第 11 票历史结果保留：失败正文与实际原因原子保存、回滚保留结算所有者、不重跑 Graph、首终态竞争、错误色标记与完整原因查看、重开读取。显式 `gpt-6-luna / max` 完成后端新增专项 **12 通过**、最终串行完整回归 **313 项：312 通过、0 失败／错误、1 Windows 符号链接权限跳过**；前端全套 **140 通过**，样式修正后受影响专项 **6 通过**；真实 Tauri 首轮覆盖 **24 项：22 通过、2 失败**，随后本票最终 **1 通过**、旧 IME 原样隔离诊断 **1 通过**，未将隔离通过改算为完整批次全通过。专项与完整套件重叠，不相加。最终 TypeScript／构建、9 个唯一 Python 文件 Ruff、产品及新增测试 ty 通过；本票无 Rust 产品改动，未重复 Rust 构建或测试。Standards／Spec 0 项剩余硬问题。完整过程、历史失败、六条验收证据、日志、截图与覆盖边界见[第 11 票报告](../../../../.scratch/frontend-completion/ticket-11/report.md)。

第 10 票历史结果保留：后端专项 10 通过，最终串行全套 301 项中 300 通过、0 失败／错误、1 Windows 符号链接环境跳过；前端 Node 134 通过；真实 Tauri 单个 runner 串行新 4＋旧 19＝23 个唯一用例通过。TypeScript／构建／11 文件 Ruff／产品及测试范围 ty 通过，Standards／Spec 无剩余硬性问题。完整过程与历史失败见[第 10 票报告](../../../../.scratch/frontend-completion/ticket-10/report.md)。

第 9 票历史结果保留：前端首轮全套 121 通过，修复后受影响四个文件 56 通过（有重叠）；Rust 25 通过；后端 291 项中 290 通过、1 环境跳过；真实 Tauri 分批 19 个唯一用例通过。第 10 票原生回归捕获 Home 因亚像素锚点抖动被回写打断，窄修复后三个阅读位置用例均通过，未改变原断言。物理 Windows 输入、系统 IME、窗口边框及多尺寸联合验收仍归第 23 票；工作目录资源访问归第 14 票。历史[第 9 票](../../../../.scratch/frontend-completion/ticket-09/report.md)、[第 8 票](../../../../.scratch/frontend-completion/ticket-08/report.md)、[第 7 票](../../../../.scratch/frontend-completion/ticket-07/report.md)、[第 6 票](../../../../.scratch/frontend-completion/ticket-06/report.md)、[第 5 票](../../../../.scratch/frontend-completion/ticket-05/report.md)及[第 4 票](../../../../.scratch/frontend-completion/ticket-04/report.md)证据保留。

**保留的回归问题：**第4票的审批恢复结算超时在第5、6、7票完整回归中未复现，但未修改路径或确认根因，[旧问题](../../../../.scratch/approval-cleanup-test-timeout/issues/01-approval-resume-settlement-timeout.md)仍为needs-triage。第7票完整回归另出现空宿主环境变量分支的进程退出等待超时，正式隔离两次通过，原因未确认，见[新的独立问题](../../../../.scratch/desktop-environment-exit-timeout/issues/01-empty-host-environment-startup-exit.md)及[第7票后端报告](../../../../.scratch/frontend-completion/ticket-07/backend-report.md)。历史失败不改算通过。

第 8、9 票完整回归中上述两个正式用例均通过，未修改相关产品路径或确认根因，两份 needs-triage 记录继续保留。第 7 票的历史完整回归结果仍为 289 通过、1 错误、1 跳过，不能用本次通过覆盖，见[第 8 票后端报告](../../../../.scratch/frontend-completion/ticket-08/backend-report.md)及[第 9 票后端报告](../../../../.scratch/frontend-completion/ticket-09/backend-report.md)。

第 10 票较早完整回归再次出现审批结算同一 3 秒超时（299 通过、1 错误、1 跳过）；原生结束后的正式隔离两次为 1 通过／1 错误，最终单次串行全套未复现。未确认根因或与本票结算互斥变更的关系，旧问题继续 needs-triage，不能以最终通过抵消历史失败。两轮原生失败及第二轮发送前 Failed to fetch 也保留，详见[第 10 票报告](../../../../.scratch/frontend-completion/ticket-10/report.md)。

第 11 票完整后端回归未报上述两个历史超时，仍未确认根因。原生首轮新专项的纵滚夹具问题已修且保留断言；旧第 04 票 IME Enter 没有 POST、等待历史超时，原样隔离通过但原因与稳定性未知，新增[IME 待排查记录](../../../../.scratch/native-ime-enter-timeout/issues/01-composition-enter-no-post.md)。物理输入与系统 IME 验收仍归第 23 票。历史失败不改算通过。

实施由用户主导。ready-for-agent 表示任务描述自足；每票使用“待实施／实施中／待验收／已验收”记录实施进度，验收完成后才能将该票 Status 改为 done。后续使用 /implement 时仍遵守代码自主权约定。

共同要求：

- 每票完成用户可见的端到端路径，所需持久契约、公开接口／原生命令、客户端、UI 和边界验证在对应票内落实，优先复用既有能力。
- 各批新增组件从开始继承[设计规范](../../../../frontend/design.md)，实施阶段参照[八批计划](../tickets/006-interaction-acceptance.implementation.md)。阻塞边仅列完整标题的直接前提。
- 验证用户行为、公开请求／响应和已提交事实，优先使用现有 HTTP／SSE、BackendSession、Runtime 和原生验收入口，具体错误就地反馈并保留事实和输入。
- 状态权威、字段省略／null、目标失效、重试、Retry-After 和未知写入结果沿用定稿规格，所有写操作由用户主动，结果未知先 GET 核实。
- 每票的边界验证由实施者执行记录，最终联合验收补齐跨分支及真实 Tauri 证据；本轮票据的发布不代表实现或验收通过。

## 票据与直接依赖

| 序号 | 实施票据 | Blocked by |
| --- | --- | --- |
| 01 | [打开会话并核实运行状态](01-open-conversation-run.md) | 无，可立即开始 |
| 02 | [自动分页浏览带状态的会话列表](02-paginated-conversation-list.md) | [打开会话并核实运行状态](01-open-conversation-run.md) |
| 03 | [全量重建消息与当前运行事实](03-run-fact-reconstruction.md) | [打开会话并核实运行状态](01-open-conversation-run.md) |
| 04 | [原文发送并保留持久消息草稿](04-message-drafts-send.md) | [全量重建消息与当前运行事实](03-run-fact-reconstruction.md) |
| 05 | [断流后的有限 GET 恢复与手动重连](05-stream-recovery.md) | [全量重建消息与当前运行事实](03-run-fact-reconstruction.md) |
| 06 | [隐藏暂停读取并轮询会话状态](06-visibility-polling.md) | [自动分页浏览带状态的会话列表](02-paginated-conversation-list.md)；[原文发送并保留持久消息草稿](04-message-drafts-send.md)；[断流后的有限 GET 恢复与手动重连](05-stream-recovery.md) |
| 07 | [安全 Markdown、网页链接与完整内容查看](07-markdown-content-viewer.md) | [全量重建消息与当前运行事实](03-run-fact-reconstruction.md) |
| 08 | [完整呈现工具调用、结果与附加数据](08-complete-tool-records.md) | [安全 Markdown、网页链接与完整内容查看](07-markdown-content-viewer.md) |
| 09 | [恢复聊天阅读位置与自动跟随](09-chat-reading-position.md) | [全量重建消息与当前运行事实](03-run-fact-reconstruction.md) |
| 10 | [确认取消并保存已生成的中止正文](10-cancel-partial-message.md) | [原文发送并保留持久消息草稿](04-message-drafts-send.md)；[断流后的有限 GET 恢复与手动重连](05-stream-recovery.md)；[安全 Markdown、网页链接与完整内容查看](07-markdown-content-viewer.md) |
| 11 | [执行失败后保存已生成的中止正文](11-failure-partial-message.md) | [确认取消并保存已生成的中止正文](10-cancel-partial-message.md) |
| 12 | [逐项审批并继续同一运行](12-approval-resume.md) | [确认取消并保存已生成的中止正文](10-cancel-partial-message.md) |
| 13 | [恢复审批草稿并核实未知提交](13-approval-draft-recovery.md) | [隐藏暂停读取并轮询会话状态](06-visibility-polling.md)；[逐项审批并继续同一运行](12-approval-resume.md) |
| 14 | [自动预览工作目录内的本地图片](14-workspace-image-preview.md) | [隐藏暂停读取并轮询会话状态](06-visibility-polling.md)；[安全 Markdown、网页链接与完整内容查看](07-markdown-content-viewer.md)；[恢复聊天阅读位置与自动跟随](09-chat-reading-position.md) |
| 15 | [每次确认后用系统程序打开工作目录文件](15-workspace-file-open.md) | [自动预览工作目录内的本地图片](14-workspace-image-preview.md) |
| 16 | [导出已提交会话与完整工具记录](16-conversation-export.md) | [完整呈现工具调用、结果与附加数据](08-complete-tool-records.md)；[执行失败后保存已生成的中止正文](11-failure-partial-message.md) |
| 17 | [查看当前运行详情与真实累计用量](17-run-details-usage.md) | [隐藏暂停读取并轮询会话状态](06-visibility-polling.md)；[安全 Markdown、网页链接与完整内容查看](07-markdown-content-viewer.md) |
| 18 | [查看已提交运行事件与审批历史](18-run-events-history.md) | [查看当前运行详情与真实累计用量](17-run-details-usage.md) |
| 19 | [有限核实待结算用量](19-usage-settlement.md) | [查看当前运行详情与真实累计用量](17-run-details-usage.md) |
| 20 | [会话标题、日期时间与空态引导](20-conversation-titles-time-empty-state.md) | [自动分页浏览带状态的会话列表](02-paginated-conversation-list.md)；[原文发送并保留持久消息草稿](04-message-drafts-send.md) |
| 21 | [原稿风格的响应式导航与桌面偏好](21-responsive-navigation.md) | [自动分页浏览带状态的会话列表](02-paginated-conversation-list.md)；[原文发送并保留持久消息草稿](04-message-drafts-send.md)；[安全 Markdown、网页链接与完整内容查看](07-markdown-content-viewer.md)；[恢复聊天阅读位置与自动跟随](09-chat-reading-position.md) |
| 22 | [本地命令面板与受限全局快捷键](22-command-panel-shortcuts.md) | [查看当前运行详情与真实累计用量](17-run-details-usage.md)；[会话标题、日期时间与空态引导](20-conversation-titles-time-empty-state.md)；[原稿风格的响应式导航与桌面偏好](21-responsive-navigation.md) |
| 23 | [首版 Tauri 全流程与原稿实机验收](23-native-workflow-acceptance.md) | [恢复审批草稿并核实未知提交](13-approval-draft-recovery.md)；[每次确认后用系统程序打开工作目录文件](15-workspace-file-open.md)；[导出已提交会话与完整工具记录](16-conversation-export.md)；[查看已提交运行事件与审批历史](18-run-events-history.md)；[有限核实待结算用量](19-usage-settlement.md)；[本地命令面板与受限全局快捷键](22-command-panel-shortcuts.md) |

只列直接阻塞关系；各票的状态、实施进度和验收记录以对应文件为准。阻塞票验收完成并标记 done 后，其后继票进入可开始集合。
