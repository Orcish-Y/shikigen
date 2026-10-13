---
id: tools-mainstream-fields
title: 调查主流 Agent 的工具录入项与发现机制
parent: tools-workflow
labels: ["wayfinder:research"]
mode: AFK
status: closed
assignee: codex
blocked_by: []
research_branch: research/tool-configuration-fields-20261012
research_commit: 896e4bc216d7d4419b6cc114cb59188ff56c8a04
resolution: 001-mainstream-tool-fields.resolution.md
---

# 调查主流 Agent 的工具录入项与发现机制

## Question

从 LangChain、Dify、AutoGen、Claude Code / DeerFlow 等有代表性的官方文档和源码，以及 MCP 规范，调查工具共有字段、MCP 服务连接字段及自动发现字段、Python 代码与 HTTP 工具配置。区分必填、可选、自动生成、运行时参数和产品自身管理字段，并给出适合学习项目的最小录入项建议。

重点回答：工具名称/说明/输入 schema/输出 schema 的用途，MCP 连接与工具的关系，stdio 与 Streamable HTTP 连接字段，Python 入口及输入输出约定，HTTP 认证及参数位置，适配器如何接入已有 BaseTool。标出来源、调查日期、版本或证据边界；不把某产品字段当成通用标准，不代替用户完成产品决策。

用户进一步确认首版需要 OpenAPI 导入：补充官方规范与代表产品的导入字段、操作选择、JSON/YAML、版本、servers、parameters、requestBody、schema 引用及 security 映射依据。区分导入工具定义与运行时发送 HTTP 的适配器。

## Context

- [现状调查](../baseline.md)
- 研究产物：`docs/research/tool-configuration-fields.md`；单文件保存全部来源与推荐理由。
- 使用 research skill；产物另存到 front matter 指定的研究分支并推送，不开 PR、不合并。保持当前工作区与用户 Git 索引。

## 研究资产

- [工具配置字段与适配器调查](../../../research/tool-configuration-fields.md)：完整来源、字段表、OpenAPI 导入子集建议和证据边界。
- [研究分支中的调查报告](https://github.com/Orcish-Y/shikigen/blob/research/tool-configuration-fields-20261012/docs/research/tool-configuration-fields.md)：已推送的单文件研究产物。
- [调查决议](001-mainstream-tool-fields.resolution.md)：研究票据结论与后续上下文。

