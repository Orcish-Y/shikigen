---
id: frontend-message-tools-export
title: 确定真实消息、工具与导出的呈现
parent: frontend-completion
labels: ["wayfinder:grilling"]
mode: HITL
status: closed
assignee: codex
blocked_by: []
resolution: 004-message-tools-export.resolution.md
---

# 确定真实消息、工具与导出的呈现

## Question

真实 content 如何安全呈现 Markdown、代码和 block 数组？AI tool_calls 与 ToolMessage 如何通过 tool_call_id 关联参数、结果、artifact 和事实状态？导出如何保证只包含已提交内容？

**做什么：**决定真实消息的展示模型、工具展开层级、长输出处理、安全 Markdown 渲染方案与 Markdown 导出范围。

**为什么：**当前漂亮的 CodeBlock 由示例 code 字段驱动；真实消息只显示纯文本，工具调用拼入正文，结果另作 Agent 行，artifact 未进入类型。导出也没有排除当前 delta。

**已有 API：**Thread/Run messages 与 event.category=message；AIContent.tool_calls、ToolContent.tool_call_id/name/status/artifact。正文纯文本目前经 React 安全转义，不需要把现状误判为 HTML 注入。

**需要决定的边界：**保持用户浅灰/Agent 白画布的现有层级；代码复制原始完整内容；未知对象完整只读展示，不能只保留 text 字段；无结果只显示“等待结果”；失败图标与文字一致；不展示伪造耗时与推测执行状态。导出标明已加载范围，不包含草稿和预览。

## 已确认上下文

[运行投影与恢复契约](002-run-projection.contract.md)提供保留完整字段的已提交消息与独立预览，按会话 seq 合并。观察重建保留完整消息，仅重新积累目标 Run 的未提交预览；这些目标仍待实施。本票据继续决定真实呈现与导出，不将临时预览当成已提交事实。

[审批与取消交互契约](003-approval-cancel.contract.md)已确定参数默认折叠、完整查看与复制、审批草稿保存和真实已处理状态。取消保留已有完整消息和工具结果；本地未提交审批选择或原因不属于可作为已处理事实导出的内容。本票据继续决定消息／工具的展开层级及已提交导出范围。

## 关联资产

- [消息、工具、导出与本地资源契约](004-message-tools-export.contract.md)：已完整确认的实施目标，行为及新增接口待实施。
- [决议](004-message-tools-export.resolution.md)：最终确认、关闭与后续上下文。
- [消息、工具与导出的讨论记录](004-message-tools-export.discussion.md)：源码事实、逐项选择和完整核对过程。
