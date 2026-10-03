---
id: frontend-run-details
title: 确定运行详情、用量与事件视图
parent: frontend-completion
labels: ["wayfinder:grilling"]
mode: HITL
status: closed
assignee: codex
blocked_by: ["frontend-run-discovery", "frontend-run-projection"]
resolution: 005-run-details.resolution.md
---

# 确定运行详情、用量与事件视图

## Question

当前覆盖式详情与历史栏如何完整展示当前 Run 的身份、状态、用量、事件、错误与恢复入口？基于已确认的投影规则，如何解释数据读取、未知和待结算状态？

**做什么：**确定 Thread/Run ID 复制、total_input/output/tokens、calls、by_model、usage_pending、生命周期/审批事件时间线与历史栏摘要。

**为什么：**现在只有输入/输出 token 与少量字段；历史栏永远显示未知，事件没有保存。补齐首版详情即可满足当前任务，不启用独立追踪页。

**已有 API：**metadata usage、完整 event 的 seq/created_at/event_type；新增纯读 RunSnapshot 与 events 的目标形状见已确认的[会话与运行查询契约](001-run-discovery.contract.md)，尚未实现。JSON 事件复用 SSE 的公开形状；get_backend_logs 是宿主启动 stderr，不能充当 Run 业务事件。

**需要决定的边界：**未知不显示 0；usage_pending 省略、true、false 的提示不同；已累计用量可在恢复执行时保留但仍待结算；calls 不等于供应商准确计费；事件按 seq 展示并去重；关闭抽屉不关闭观察或取消 Run；保持 400px 桌面覆盖和移动底部 Sheet。

## 前置上下文

[运行投影与恢复契约](002-run-projection.contract.md)已定稿，行为待实施。当前状态以有效 SSE metadata 为准，字段缺省不清空已知值；JSON 请求需要身份与更新检查。保留历史累计值不等于确认当前执行已结算。

本票据继续决定提示、读取时机、待结算刷新、事件布局和恢复入口位置，消费同一消息/事件投影，不另建状态权威规则。

完整方案已获用户确认，见[运行详情、用量与事件契约](005-run-details.contract.md)及[决议](005-run-details.resolution.md)。真实交流见[运行详情、用量与事件视图：讨论记录](005-run-details.discussion.md)；应用实施待完成。

[审批与取消交互契约](003-approval-cancel.contract.md)已确定以服务端 decisions 展示审批历史，以及有效取消 POST 快照立即收敛目标 Run 的真实终态；该写操作结果不同于可能过期的普通 GET。未取得真实审批事件时不伪造 resolved / invalidated，后续用量结算和事件补读的呈现由本票据决定。

[消息、工具、导出与本地资源契约](004-message-tools-export.contract.md)已定稿，新增能力待实施：中止正文由后端保存并独立标记，终态消息补读使用现有 Run messages。消息生成结果、工具结果和 Run 状态保持各自语义；本地资源读取及系统打开错误只影响所属资源。消息补读不表示用量已经结算，本票据继续决定用量与持久事件的读取和呈现。
