# 首版 Tauri 聊天工作台实施票据

Status: ready-for-agent

补齐首版真实聊天、运行恢复、审批／取消、中止正文保存、完整内容与资源、详情和导航；来源：[统一实施规格](../../../../.scratch/frontend-completion/PRD.md)。

发布日期：2026-10-04。用户已确认 23 张票据的粒度、直接阻塞依赖及拆分安排，答复“按方案定稿并发布（推荐）”。共 156 条验收条件；第 1、2 票已实现并验收，其余票据待实施。

文件组织：2026-10-04 按用户提出的目录与粒度要求，每张实施票据独立保存于本目录。本索引汇总公共要求与直接依赖；原有 [Wayfinder 地图](../map.md)及 tickets/ 记录规划决策。

工作 frontier：阻塞票全部完成的票即可开始，每次推进一票；以下按依赖顺序编排，独立分支可自行安排。2026-10-04 第 1、2 票已完成；本轮收尾：**第 2 票“自动分页浏览带状态的会话列表”**（已补修桌面 CORS；Python 285 项通过、1 项环境跳过，真实分页、过滤、503 重试、422 重载、长对话活动 SSE 隔离及可信 WebView End／PageDown 输入均已补证）。当前下一票：**第 3 票“全量重建消息与当前运行事实”**；本轮未启动第 3 票。物理 Windows 输入、窗口边框及多尺寸联合验收仍归第 23 票。

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
