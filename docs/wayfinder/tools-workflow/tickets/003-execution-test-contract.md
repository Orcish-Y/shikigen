---
id: tools-execution-tests
title: 确定 MCP、Python 与 HTTP 的执行和测试边界
parent: tools-workflow
labels: ["wayfinder:grilling"]
mode: HITL
status: closed
assignee: codex
blocked_by: [tools-definition-adapters, tools-openapi-import]
resolution: 003-execution-test-contract.resolution.md
---

# 确定 MCP、Python 与 HTTP 的执行和测试边界

## Question

首版三类工具分别以什么配置与输入执行，统一返回什么成功/失败结果？MCP 连接测试、工具发现和真实调用，Python 代码入口/参数/返回值/运行环境，以及 HTTP 按已确认映射执行、凭据与响应处理分别怎样约定？

依赖：[确定工具定义、适配器与稳定引用契约](002-definition-adapters-references.md)、[确定 OpenAPI 导入的首版范围](005-openapi-import-scope.md)；按需引用[主流 Agent 调查](001-mainstream-tool-fields.md)。

工具定义和适配器的已确认约束见[定义、适配器与引用决议](002-definition-adapters-references.resolution.md)；本票据明确专属执行字段与调用契约。

HTTP 的兼容子集、输入分组、映射一致性、认证范围与可选输出结构见[OpenAPI 导入范围决议](005-openapi-import-scope.resolution.md)。本票据在这些约束下明确实际输入校验（含 format 注解）、参数转换及空值处理、凭据录入与保存、请求超时及统一返回行为。

需要用户决定的边界：代码采用本机进程还是宿主内执行、依赖录入范围、超时与取消的实际保证、测试已保存或未保存的配置、认证信息录入/引用/回显、错误与原始结果显示，以及未来 Agent 调用和手动测试如何复用执行入口。统一入口还需校验输入 schema 与实际参数；当前 BaseTool 接收字典 schema 时不会完成 JSON Schema 校验。MCP 结果可能含多个内容块与 artifact，不能只因测试面板简单而丢掉底层数据。首版不承诺生产沙箱或自动撤销外部操作。

