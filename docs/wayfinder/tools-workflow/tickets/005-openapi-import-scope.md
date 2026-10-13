---
id: tools-openapi-import
title: 确定 OpenAPI 导入的首版范围
parent: tools-workflow
labels: ["wayfinder:grilling"]
mode: HITL
status: closed
assignee: codex
blocked_by: [tools-definition-adapters]
resolution: 005-openapi-import-scope.resolution.md
---

# 确定 OpenAPI 导入的首版范围

## Question

用户已确认 HTTP 首版需要 OpenAPI 导入。学习项目最小支持哪些文档输入、版本与格式，以及什么导入规则，能够选择接口并生成可以真实执行的单请求 HTTP 工具？

依赖：[确定工具定义、适配器与稳定引用契约](002-definition-adapters-references.md)；依据：[主流 Agent 调查](001-mainstream-tool-fields.md)。

导入器生成的定义与命名需遵循[定义、适配器与引用决议](002-definition-adapters-references.resolution.md)；本票据决定 HTTP 专属字段的生成及导入边界。

需要用户决定的边界：上传/粘贴/URL，JSON/YAML 与 OpenAPI 版本范围，选择 operations、servers 与 operationId 缺失/冲突，path/query/header 参数、requestBody 和 schema 引用的解析范围，security 与实际认证信息如何绑定，复杂结构或不支持项如何明确反馈，以及导入后能否手工编辑、重复导入是否覆盖已有工具。

导入器负责生成统一工具定义；运行适配器负责执行 HTTP。首版不做多请求编排，是否同时提供从空白表单手工创建接口需明确，不能由“支持导入”自动推断。

