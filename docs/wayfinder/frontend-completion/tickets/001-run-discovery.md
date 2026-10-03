---
id: frontend-run-discovery
title: 确定会话 Run 发现与只读查询契约
parent: frontend-completion
labels: ["wayfinder:grilling"]
mode: HITL
status: closed
assignee: codex
blocked_by: []
resolution: 001-run-discovery.resolution.md
---

# 确定会话 Run 发现与只读查询契约

## Question

首版如何直接定位某个 Thread 的 active Run、最近 Run 与历史 Run？采用会话 Run 列表、Thread 的 active_run，还是组合？返回字段、排序、分页、状态语义及普通 Run 快照/事件查询应如何定义？

**做什么：**确定 PRD 第 14 节 P0.1/P0.2 的 HTTP 契约，并说明基于历史消息最后一个 run_id 的现有恢复路径如何过渡。

**为什么：**目前并非完全无法刷新恢复，但没有直接 Run 发现与历史查询契约。普通刷新和恢复不应依赖前端扫描全部对话来推断任务。

**已有 API：**GET Thread messages、GET Run stream、GET Run messages；RunService.read_run 与 list_run_events 已存在，尚未暴露为 HTTP。RunSnapshot 的身份为 id，SSE metadata 为 run_id。

**需要决定的边界：**查询只读且验证 Thread/Run 归属；明确 active 无值与 Thread 不存在的区别；明确是否提供使用完整 PRD 所需的近期运行信息；新列表分页参数不改变 SSE 无 cursor 的契约。依据见[差距审计](../../../frontend/frontend-gap-audit.md)。

## 讨论资产

- [讨论记录](001-run-discovery.discussion.md)：保留会话入口、状态、恢复、分页与轮询的实际讨论过程。
- [会话与运行查询契约](001-run-discovery.contract.md)：用户已确认的完整字段、分页、恢复与纯读边界。
- [决议](001-run-discovery.resolution.md)：最终确认及后续票据的上下文指针。
