---
id: tools-definition-adapters
title: 确定工具定义、适配器与稳定引用契约
parent: tools-workflow
labels: ["wayfinder:grilling"]
mode: HITL
status: closed
assignee: codex
blocked_by: [tools-mainstream-fields]
resolution: 002-definition-adapters-references.resolution.md
---

# 确定工具定义、适配器与稳定引用契约

## Question

三类工具如何统一成可保存、可选择和可调用的工具定义，并通过类型适配器接入已有 BaseTool / ToolRegistry？公共字段、类型专属字段或子模型、持久 ID、模型调用名、输入 schema、可选输出 schema 与 MCP 连接身份分别属于哪一层？

依据：[调查主流 Agent 的工具录入项与发现机制](001-mainstream-tool-fields.md)。

需要用户决定的边界：MCP 发现工具的保存与选择方式，同名冲突如何反馈，工作流与定制 Agent 未来按何种身份引用，新增类型如何扩展，以及尚未实现工作流时需要预留到什么程度。用“两个 MCP 服务都提供 search”与“工具改名后已有引用”的情形核对边界。保持一个小接口和现有 Registry，不建设插件市场。

