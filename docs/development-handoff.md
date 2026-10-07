# 开发交接与当前状态

整理日期：2026-10-07。本页依据现有实施票据、开发报告和工作区盘点编写；本次文档整理没有重新执行产品测试。历史测试数量属于各自源码阶段，不合并为当前版本全仓通过。

## 接手顺序

1. 阅读 [领域词汇](../CONTEXT.md)、[项目架构与接口](project.md)；理解 Thread、Run、执行 invocation、运行事实和流式预览的区别。
2. 桌面开发先读 [Windows 开发说明](windows-development.md)、[前端启动说明](../frontend/README.md)、[桌面生命周期](windows-backend-lifecycle.md)。
3. 前端行为以 [已定稿契约](wayfinder/frontend-completion/tickets/006-interaction-acceptance.contract.md)、[23 张实施票据](wayfinder/frontend-completion/implementation/index.md)及代码为准；视觉以 [frontend/design.md](../frontend/design.md) 为准。
4. 修改消息持久化前读 [统一消息写入与结算报告](archive/2026-10-07/development/message-write-refactor/report.md)，修改桌面启动前读下表中的两份端口报告。
5. 先核对下方遗留问题，再确定回归范围；不要把旧规格里的“待实施”直接当作新任务。

## 已完成的工作

| 主题 | 已有结果 | 详细记录 |
| --- | --- | --- |
| Windows 后端托管 | 生命周期、数据独占、受控 Python 启动、日志、托盘与 HTTP/SSE 接入 | [生命周期摘要](windows-backend-lifecycle.md)、[最终协议](wayfinder/windows-backend-lifecycle/tickets/002-runtime-contract.resolution.md) |
| 首版聊天工作台 | 1–23 票全部 done：真实会话、恢复、审批、取消、完整工具内容、本地资源、导出、用量、事件、导航及快捷键 | [实施索引](wayfinder/frontend-completion/implementation/index.md)、[原生验收汇总](wayfinder/frontend-completion/native-acceptance-summary.md) |
| 显式会话页长 | 所有列表请求显式传 limit，默认前端页长 20，支持跨页改变及极大整数边界 | [分页调整报告](archive/2026-10-07/development/thread-page-limit/report.md) |
| 统一消息事务 | 正常、取消、失败消息复用 writer；正文与运行结算原子提交，回滚保留缓冲与执行所有者 | [事务重构报告](archive/2026-10-07/development/message-write-refactor/report.md) |
| 查询响应策略 | 查询响应头集中生成，每次响应独立复制，保留 no-store 等公开契约 | [验证报告](archive/2026-10-07/development/query-response-headers/report.md) |
| 开发端口回退 | Vite 实际 URL 传入 Tauri 和后端精确 CORS；使用 pnpm tauri dev 进入协调流程 | [端口回退报告](archive/2026-10-07/development/dev-port-fallback/report.md) |
| 桌面网络模块 | desktop_network 承接监听与 origin 校验；start_port 与 bound_port 语义明确；共享 Python/Rust 配置案例 | [网络整理报告](archive/2026-10-07/development/desktop-network-refactor/report.md) |

桌面网络模块报告对应工作区中的未提交源码/测试。本次整理会保留它们；报告归档不表示已经提交或发布。

## 验证基线与实际限制

- 第 23 票：后端 334 项中 333 通过、1 权限跳过；前端完整 269 通过，最后受影响专项 20 通过；Rust 35 通过。分批原生验收的范围和历史失败见 [完整报告](archive/2026-10-07/development/frontend-completion/ticket-23/report.md)。
- 端口回退：Node 完整 278 通过；后端完整 338 项中 336 通过、1 错误、1 跳过，**该批完整回归未通过**。错误是审批恢复结算等待超时，见 [后端报告](archive/2026-10-07/development/dev-port-fallback/validation/backend/report.md)。
- 网络模块：相关 Python 69 通过、Rust 完整 36 通过、Node 启动专项 9 通过；没有重跑全仓 Python 或实际 WebView/HMR。
- Windows 符号链接权限跳过、既有全仓 Ruff 问题、Vite 大 chunk 提示，以及安装包/Python 分发和 macOS 原生未验范围继续保留。
- OS 输入/触控注入已有证据；实体外设、TabTip、候选窗口画面、OSK 点键和保存弹窗取消仍有覆盖缺口，见 [原生汇总](wayfinder/frontend-completion/native-acceptance-summary.md)。

## 未解决的问题

这三项保持原来的 needs-triage 状态，本次没有修复或关闭：

| 问题 | 后续需要核实 |
| --- | --- |
| [审批恢复结算等待超时](issues/approval-resume-settlement-timeout.md) | 2026-10-07 端口回退全仓回归再次出现；保持原断言，区分生命周期缺陷与执行耗时敏感的等待窗口 |
| [空宿主环境进程退出超时](issues/empty-host-environment-startup-exit.md) | 捕获进程启动、退出与管道读取时间线；隔离通过不代表根因已解决 |
| [原生 IME 后 Enter 间歇不发送](issues/composition-enter-no-post.md) | 在完整顺序中记录 composition、Enter、焦点及发送资格；后续系统 IME 成功不倒推历史失败已修复 |

## 文档如何使用

`docs/project.md` 与最终契约描述当前设计；`docs/wayfinder/` 保存决策及实施状态；`frontend/design.md` 是当前设计依据。`design/` 保留用户提供的两份 HTML 原稿及两张参考图，旧 design.md 仅供设计沿革阅读。

[本次归档](archive/2026-10-07/README.md)保留可直接阅读的开发指导 Markdown；历史报告、少量未决问题和最终原生验收证据分主题压缩。常规成功日志、重复运行附件和无必要的截图/JSON 已删除。归档正文中的状态、命令、绝对路径与测试数字保留原阶段含义，先读本页判断是否仍适用。编译缓存和重复源码快照已清理，不能再依赖旧 scratch 快照复现。

`.scratch/` 与 `frontend/.scratch/` 用于本地临时产物，已配置忽略规则；本次清空。既有技能的临时任务目录约定不变，后续交接请引用已经归档的长期文档。学习进度仍见 [NOTES.md](../NOTES.md)，它不替代产品交付状态。
