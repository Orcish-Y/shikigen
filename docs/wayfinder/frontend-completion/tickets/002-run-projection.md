---
id: frontend-run-projection
title: 确定运行投影、观察连接与错误恢复
parent: frontend-completion
labels: ["wayfinder:grilling"]
mode: HITL
status: closed
assignee: codex
blocked_by: ["frontend-run-discovery"]
resolution: 002-run-projection.resolution.md
---

# 确定运行投影、观察连接与错误恢复

## Question

前端如何分别维护宿主状态、观察连接状态、Run 快照、完整消息、delta 和审批事实？重连、切换、刷新与迟到响应如何收敛，同时不重复 POST 或丢失用户输入？

**做什么：**明确前端事实投影与恢复入口，覆盖已知 Run 重建、尚未取得 run_id 的结果未知、404/409/422/500/503、Retry-After、观察 error 与 lifecycle error；确定会话列表轮询、历史消息状态、JSON 查询和 SSE 的合并规则。

**为什么：**当前元数据合并与 seq 去重可继续使用，但 approval、事件时间线、连接状态与结构化 HTTP 错误没有进入完整状态模型。原始发送草稿在异步失败前已清空，也需要明确保留与恢复规则。

**已有 API：**fetch SSE、GET Run stream；新增查询目标见已确认的[会话与运行查询契约](001-run-discovery.contract.md)，尚未实现。HTTP 客户端仍绑定 startup_id、base_url 和 AbortSignal，避免旧启动污染当前会话。

**需要决定的边界：**完整事实覆盖同 seq 预览；历史生命周期不覆盖 metadata 的当前快照；终态 EOF 正常，观察失败不变更 Run 为 error；本地 run_id 是恢复线索；发送/审批接受状态未知时仅先读取事实；草稿、消息、审批选择按 Thread/Run 隔离。

**前置契约带来的待决问题：**如何防止迟到的第一页轮询或 JSON 快照覆盖较新的 SSE 状态；如何区分游标 422 和审批 422；纯读查询 500 / 503 时如何保留可读数据和恢复入口；如何分别维护列表分页进度、选择、后端启动身份与 Run 观察身份。

## 讨论资产

- [运行投影与恢复契约](002-run-projection.contract.md)：用户已确认，接口与行为待实施。
- [决议](002-run-projection.resolution.md)：最终确认及后续上下文。
- [运行投影、观察连接与错误恢复讨论记录](002-run-projection.discussion.md)：源码事实与真实交流历史。
