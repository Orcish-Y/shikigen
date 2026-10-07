---
id: frontend-completion
title: 首版聊天工作台与后端恢复补全决策地图
labels: ["wayfinder:map"]
status: closed
assignee: null
---

# 首版聊天工作台与后端恢复补全决策地图

## Destination

以完整前端 PRD 的首版 17 条验收标准及用户补充的中止消息保存、本地资源呈现要求为目标，明确当前 Tauri 聊天工作台的缺失功能、后端恢复查询接口、前端事实投影、样式继承和实施依赖，形成可以交给用户实现的方案。
地图完成表示首版实现前的产品行为与接口决策已明确，不表示应用已实现或通过测试。

## Notes

- 用户于 2026-10-03 确认：前后端一起补齐；首轮完成首版聊天工作台与后端恢复接口，工具、系统设置、独立运行追踪等页面留到后续。
- 用户补充要求：取消／失败也保存已生成消息；聊天中当前 Agent 工作目录内的本地图片自动预览，本地文件经确认弹窗后打开。这些能力纳入首版方案。
- 实际应用位于 frontend/，采用 Tauri。Windows 宿主就绪后已有真实 HTTP/SSE 接入；直接浏览器访问为示例预览。既有后端托管、单实例、托盘与动态地址方案作为已实现基线。
- 当前依据：[PRD](../../frontend/frontend-prd.md)、[差距审计](../../frontend/frontend-gap-audit.md)、[当前设计规范](../../../frontend/design.md)、实际路由/契约/组件。旧阶段记录不自动成为当前完成度结论。
- 本轮按用户明确请求整理现状审计与 design.md，作为建图输入；允许在建图时完成这两项文档工作，不据此关闭任何子票据或执行应用实现。
- 新组件必须延续白色画布、冷灰双侧栏、靛蓝强调色、Geist/JetBrains Mono、Phosphor regular、细边框与紧凑控件。用户于 2026-10-03 补充两份 HTML 原稿及项目截图，明确要求尽量贴近原稿；目标与当前实现差异在 design.md 中维护。
- 已直接查看用户提供的[项目展开截图](../../../design/pic/展开.png)与[项目收起截图](../../../design/pic/收起.png)，取得桌面两态的静态证据，见[视觉取证记录与清单](tickets/007-native-style-baseline.evidence.md)。用户已确认先定稿视觉基准，其余实机检查纳入实施后验收；规划关闭不表示这些检查已经通过。
- 使用 wayfinder；决策讨论使用 grilling 与 domain-modeling，沿用 Thread、Run、RunExecution、观察连接、Interrupt 的现有含义，已确认用语见[领域词汇](../../../CONTEXT.md)。用户负责代码，未授权修改 Git、暂存或提交。
- 本目录 tracker 见 [本地追踪规则](tracker.md)。每次只认领并处理一个决策票据；建图会话不同时解决票据。开放子票据通过元数据查询，地图正文只索引已关闭的决策。
- 2026-10-04 用户已完整确认最后的交互、实施与验收安排；七项子决策均已关闭，地图规划完成。应用代码及实机验收分别按实施计划推进，不由 closed 状态推断完成。
- 2026-10-04 按用户的 to-spec 请求，综合本地图及定稿契约发布[首版实施规格](../../archive/2026-10-07/development/frontend-completion/PRD.md)，本地 tracker 状态为 ready-for-agent，包含用户故事、实施决策、测试边界和验收矩阵。

## Decisions so far

- [确定会话 Run 发现与只读查询契约](tickets/001-run-discovery.md) — 通过会话分页列表与历史消息定位运行，恢复沿用 SSE，详情增加纯读 JSON 查询。
- [确定运行投影、观察连接与错误恢复](tickets/002-run-projection.md) — 以 SSE 投影当前运行，按会话保存输入，意外断流只通过受限 GET 恢复。
- [确定审批与取消的完整交互](tickets/003-approval-cancel.md) — 逐项审批、折叠参数并保存选择，取消经确认后按后端真实结果收敛。
- [确定真实消息、工具与导出的呈现](tickets/004-message-tools-export.md) — 保留完整消息与工具记录，补中止保存、工作目录资源与确认打开，按已提交快照导出。
- [确定运行详情、用量与事件视图](tickets/005-run-details.md) — 沿用详情抽屉，按需读取快照与事件，分别呈现运行结果和用量结算。
- [复核当前 Tauri 界面的视觉基准](tickets/007-native-style-baseline.md) — 依据原稿与桌面两态定稿样式，剩余实机检查纳入实施后验收。
- [确定首版交互补全与验收顺序](tickets/006-interaction-acceptance.md) — 定稿输入、会话浏览、阅读、命令与窄屏交互，以八批任务覆盖首版及实施后验收。

## Not yet specified

无尚未明确的首版实现前问题。长内容与提示并存、未知异常的处理范围及实机验收责任已在[交互与实施收尾决议](tickets/006-interaction-acceptance.resolution.md)明确；具体实现缺陷留在实施后核对。

## Out of scope

- 本地图不代写应用代码；后续实施由用户主导，需另行明确委托时再协助实现。
- 工具/MCP 管理、系统设置、独立运行日志与追踪页面本轮不启用；独立历史 Run 列表及导航随运行追踪能力留到后续。API 缺口记录在差距审计，新页面的样式继承记录在 design.md。
- 知识库、提示词与评估、附件上传及其他媒体能力、模型切换、reasoning、费用、协作与账号等 PRD 明确的后续或未支持能力，不作为首版补全承诺；用户明确要求的本地图片预览与本地文件确认打开已纳入首版。
- 安装包/Python 分发、macOS/Linux 原生生命周期、后端自动重启、跨进程自动续跑与外部工具副作用幂等，属于其他 effort；当前 Windows 生命周期方案继续沿用。
- 不修改 AGENTS.md 或新增工作区协作约定，不操作 Git 索引、暂存和提交。
