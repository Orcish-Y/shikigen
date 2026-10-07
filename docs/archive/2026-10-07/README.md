# 2026-10-07 开发文档归档

先读 [开发交接](../../development-handoff.md)、[实施索引](../../wayfinder/frontend-completion/implementation/index.md)和[待调查问题](../../issues/README.md)。本次仅整理文档，没有重新运行产品测试。

## 保留在外的开发指导

| 主题 | 入口 |
| --- | --- |
| 首版规格及拆分依据 | [PRD](development/frontend-completion/PRD.md)、[票据拆分](development/frontend-completion/tickets.proposal.md) |
| 首版验收结论与覆盖限制 | [联合报告](development/frontend-completion/ticket-23/report.md)、[操作边界](development/frontend-completion/ticket-23/manual-acceptance.md)、[覆盖映射](development/frontend-completion/ticket-23/coverage.md) |
| 消息写入与结算事务 | [重构报告](development/message-write-refactor/report.md) |
| 会话分页与极大整数边界 | [分页报告](development/thread-page-limit/report.md) |
| Vite/Tauri/CORS 端口回退 | [实施报告](development/dev-port-fallback/report.md)、[后端失败及诊断](development/dev-port-fallback/validation/backend/report.md) |
| 桌面网络模块 | [开发报告](development/desktop-network-refactor/report.md)、[Python 验证](development/desktop-network-refactor/validation/python/report.md)、[Rust 验证](development/desktop-network-refactor/validation/rust/report.md) |
| 查询响应策略 | [验证报告](development/query-response-headers/report.md) |
| Windows 生命周期 | [历史入口](development/windows-backend-lifecycle/README.md)，当前指导见 [生命周期文档](../../windows-backend-lifecycle.md) |

正文保留原开发阶段的状态、命令和测试计数；当前状态以开发交接为准。旧 scratch 命令需调整路径，不能认为移动后的历史脚本已经重新验收。

## 按主题压缩的材料

| 包 | 内容 |
| --- | --- |
| [frontend-history.zip](frontend-history.zip) | 前端各票历史报告、审阅、诊断和验证说明；不保留一般成功日志与多轮截图 |
| [backend-history.zip](backend-history.zip) | 后端重构、分页和启动协调的历史报告与交接说明 |
| [unresolved-issues-evidence.zip](unresolved-issues-evidence.zip) | 三项未决问题的失败日志、关键事件、截图和诊断脚本，以及旧 Windows 联合 runner |
| [native-acceptance-evidence.zip](native-acceptance-evidence.zip) | 最终原生验收的必要事实摘要、OSK 两张有效截图及清理/覆盖限制记录 |

文档链接旁的“包内”注明 ZIP 成员的完整路径。包内按原仓库相对路径保存；需要时解压到独立目录查看，外部源码引用按原仓库路径解释，不直接覆盖工作区。被删除材料的链接已明确标记，不把未保留日志说成仍可下载。

## 已删除的材料

常规成功日志、重复完整回归、旧轮次截图、通用 JSON 捕获、源码差异快照和无复现价值的临时脚本已删除。未决问题保留必要失败证据，后续成功记录保留结论，不继续保存每次重复运行的附件。删除原始产物不改变当时测试的通过、失败或跳过结论。

本轮从 1,522 个散文件收敛为 23 个文件：14 份指导 Markdown、4 个主题 ZIP、索引与核对记录。删除 1,293 份一般附件，另去重 1 份完全相同的证据；历史报告压缩保存。清单与哈希见 [manifest.json](manifest.json)，当前核对见 [document-validation.json](document-validation.json)。

## 已完成的 Git 历史清理

两个 scratch 目录已清空，并从本地和远端 master 历史移除。73 个提交的其他路径内容不变，346 个产品文件哈希不变；Git 对象降至 26.62 MiB，完整性检查通过。远端 master 已从 dfd41a8 更新为 4fb06ab。映射见 [commit-map](commit-map)，详情见 [history-cleanup.json](history-cleanup.json)。

本轮精简没有再次修改 Git 历史，也没有暂存或提交。文档留在工作区供 review。
