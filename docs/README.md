# 文档导航

更新于 2026-10-07。后续 agent 先读 [开发交接与当前状态](development-handoff.md)：首版前端 23 张票据已完成；后端近期重构、验证范围和三项待调查问题在此汇总。临时目录已迁移到 [本次归档](archive/2026-10-07/README.md)。

开发时从这里找材料。当前项目行为以 [项目开发参考](project.md)、最终接口契约及代码/测试为准；外部调查保留原调查日期，历史建议不自动成为当前待办。

| 要找什么 | 入口 | 内容 |
| --- | --- | --- |
| Harness 架构与业务契约 | [project.md](project.md) | 模块边界、持久化、消息/SSE、审批、恢复、后续任务 |
| 本地运行 | [根 README](../README.md)、[Windows 开发](windows-development.md)、[前端 README](../frontend/README.md) | 环境、启动、测试 |
| 桌面后端 | [Windows 生命周期](windows-backend-lifecycle.md) | 01～10 票实施摘要、当前能力、验收和复现 |
| 桌面接口细节 | [最终契约](wayfinder/windows-backend-lifecycle/tickets/002-runtime-contract.resolution.md) | 协议、状态、期限、单实例和托盘行为 |
| 数据锁与 Python 启动器 | [数据独占](windows-runtime-data-ownership.md)、[受控 Python 后端](windows-controlled-python-backend.md) | 开发指导与代码阅读顺序；当时的测试数字是阶段记录 |
| 前端产品与设计 | [PRD](frontend/frontend-prd.md)、[实现设计规范](../frontend/design.md)、[视觉基准决议](wayfinder/frontend-completion/tickets/007-native-style-baseline.resolution.md) | 已确认的原稿视觉要求与项目桌面差异；剩余实机检查纳入实施后验收，首版目标不表示全部已实现 |
| 首版前端补全 | [前后端差距审计](frontend/frontend-gap-audit.md)、[决策地图](wayfinder/frontend-completion/map.md)、[查询契约](wayfinder/frontend-completion/tickets/001-run-discovery.contract.md)、[运行投影与恢复契约](wayfinder/frontend-completion/tickets/002-run-projection.contract.md)、[审批与取消交互契约](wayfinder/frontend-completion/tickets/003-approval-cancel.contract.md)、[消息、工具与本地资源契约](wayfinder/frontend-completion/tickets/004-message-tools-export.contract.md)、[运行详情、用量与事件契约](wayfinder/frontend-completion/tickets/005-run-details.contract.md)、[交互与验收契约](wayfinder/frontend-completion/tickets/006-interaction-acceptance.contract.md) | 差距审计是 2026-10-03 历史快照；定稿契约保留，实施 1–23 票已完成 |
| 首版实施与验收 | [23 票实施索引](wayfinder/frontend-completion/implementation/index.md)、[原生验收汇总](wayfinder/frontend-completion/native-acceptance-summary.md) | 2026-10-07 已验收；分批结果及未覆盖硬件范围分别记录 |
| 近期开发与遗留问题 | [开发交接](development-handoff.md)、[待调查问题](issues/README.md)、[开发归档](archive/2026-10-07/README.md) | 消息事务、分页、响应头、端口回退和网络模块；保留实际回归错误 |
| 外部 Agent 架构对照 | [研究索引](research/README.md) | 持久化/执行边界、子 Agent/多会话、MCP 三个主题摘要 |
| 框架 API 速查 | [LangGraph 标识](research/langgraph-identifiers.md)、[状态存储](research/runtime-context-and-storage-strategy.md) | 开发参考，保留原文 |
| 决策依据 | [Windows 决策地图](wayfinder/windows-backend-lifecycle/map.md) | 保留已关闭票据和最终 resolution；长讨论已归档 |
| 学习与走读 | [learning-records/](../learning-records/)、[DeerFlow 架构导读](../doc/1.txt)、[run_agent 走读](../doc/带你一行行走读%20run_agent%28%29.md) | 教学材料保留，不混入当前实施待办 |
| 旧材料与验收证据 | [归档索引](archive/README.md) | 原文、日志、结果 JSON、截图、设计探索和恢复方式 |

长期目标见 [MISSION](../MISSION.md)，学习资源见 [RESOURCES](../RESOURCES.md)，协作与追踪约定保留在 [agents/](agents/issue-tracker.md)。

2026-09-24 页面框架记录见 [历史工作记录](../frontend/work-records/2026-09-24-workbench.md)。截至 2026-10-07，首版审批、取消与运行详情已纳入完成的 23 张票据；安装包分发、macOS 原生及未覆盖硬件验收继续保留。
