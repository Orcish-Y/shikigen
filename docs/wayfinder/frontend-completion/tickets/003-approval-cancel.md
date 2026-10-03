---
id: frontend-approval-cancel
title: 确定审批与取消的完整交互
parent: frontend-completion
labels: ["wayfinder:grilling"]
mode: HITL
status: closed
assignee: codex
blocked_by: ["frontend-run-projection"]
resolution: 003-approval-cancel.resolution.md
---

# 确定审批与取消的完整交互

## Question

如何在当前消息时间线、工具栏和输入区中补齐全部 Interrupt 的逐项审批、拒绝原因、提交、冲突恢复与取消，使 running/interrupted 到终态的用户路径完整？

**做什么：**确定审批卡片、长参数详情、定位入口、取消确认、pending/失效状态和恢复 SSE 的联动；遵守当前[设计规范](../../../../frontend/design.md)。

**为什么：**后端已经支持 write_file/bash 审批、同 Run 恢复和取消；当前前端仅显示 interrupted 提示，没有任何提交或取消入口。

**已有 API：**event.category=approval 的 required/resolved/invalidated；POST Run approval-decisions 返回新 SSE；POST cancel 返回 data: RunSnapshot。每个 Interrupt 的 action_requests 与 review_configs 成对，responses 以 Interrupt ID 为键，decisions 保持动作顺序。

**需要决定的边界：**一次提交全部当前决策，只提供后端允许的 approve/reject；提交失败保留选择，409 重建事实、422 显示校验问题、503 遵守 Retry-After；取消与审批竞争由后端事实决定；取消不承诺撤销已有外部副作用；折叠、切换与关闭参数层不能混淆请求归属。

## 前置上下文

[运行投影与恢复契约](002-run-projection.contract.md)已定稿，行为待实施。当前可提交审批由完整 GET 回放及当前 interrupted 状态共同确定，按 checkpoint / Interrupt 身份隔离；观察核实期间卡片只读，失效请求不能重新开放。

本票据继续确定动作界面、提交与取消、竞态和选择保存范围。HTTP 分类及不自动重发 POST 的原则沿用前置契约；JSON 查询与 GET stream 的恢复校验职责仍不同。

## 关联资产

- [审批与取消交互契约](003-approval-cancel.contract.md)：已确认的完整契约，行为待实施。
- [决议](003-approval-cancel.resolution.md)：最终确认及后续上下文。
- [讨论记录](003-approval-cancel.discussion.md)：真实逐项选择和完整核对过程。
