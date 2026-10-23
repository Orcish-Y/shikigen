# 工具库实施索引

2026-10-23 从 `.scratch/tools-workflow/issues/` 整理到版本化目录。这里保存开发票原文与完成时的记录；当前行为先读[开发指南](../README.md)，验证与报告见[验证入口](../validation.md)。原始 66 条用户故事见[历史 PRD](../../../archive/2026-10-23/tools-workflow/PRD.md)。

01–14 为开发票；上一级 `tickets/001–005` 为规划决策票。依赖列保留原拆票关系，阶段完成不代表后续延期项也已交付。

| 开发票 | 原依赖 | 实施状态与后续变化 | 实现记录 |
| --- | --- | --- | --- |
| [01 HTTP 首条链路](01-first-http-tool.md) | 无 | 已完成；后续扩展三类定义，名称候选改为前端生成 | [定义与复用](../stable-id-consumer-reuse.md)、[HTTP 参数](../http-parameters.md) |
| [02 HTTP 参数与动态表单](02-http-parameters-schema-forms.md) | 01 | 已完成；保留复杂 schema、实际输入与真假值 | [HTTP 参数](../http-parameters.md) |
| [03 编辑与草稿](03-tool-edit-drafts.md) | 01 | 已完成；响应、MCP 权限和草稿测试规则有后续修订 | [编辑与草稿](../tool-edit-drafts.md) |
| [04 HTTP 认证](04-http-auth-credentials.md) | 02 | 按调整后的范围完成认证；统一 credential 管理延期 | [认证现状](../http-auth-credentials.md) |
| [05 Python 工具](05-python-tool-execution.md) | 02 | 已完成；使用 CodeMirror 6 + Lezer，本次源码随执行快照传递 | [源码执行](../python-tool-execution.md) |
| [06 Python schema 同步](06-python-schema-sync.md) | 03、05 | 已完成；未知类型补齐、兼容补充保留与变更诊断 | [schema 同步](../python-schema-sync.md) |
| [07 stdio MCP](07-mcp-stdio-tools.md) | 04 | 主链路已完成；原票仍保留部分完成状态，统一凭据要求延期；12 补齐执行观察脱敏 | [stdio 接入](../mcp-stdio-tools.md)、[观察脱敏](../test-cancellation-lifecycle.md#可展示结果的脱敏) |
| [08 Streamable HTTP MCP](08-mcp-streamable-http.md) | 07 | 按用户确认的直接 headers 范围完成；统一隐藏编辑协议延期 | [HTTP MCP](../mcp-streamable-http.md) |
| [09 MCP 生命周期](09-mcp-discovery-lifecycle.md) | 03、07 | 已完成；选择性来源更新、未发现保留与级联删除 | [发现生命周期](../mcp-discovery-lifecycle.md) |
| [10 OpenAPI 基础导入](10-openapi-basic-import.md) | 02、03 | 已完成；引用和认证由 11 扩展 | [基础导入](../openapi-basic-import.md) |
| [11 OpenAPI 兼容与认证](11-openapi-compatibility-auth.md) | 04、10 | 已完成约定子集；认证沿用直接值 | [兼容与认证](../openapi-compatibility-auth.md) |
| [12 测试取消生命周期](12-test-cancellation-lifecycle.md) | 03、05、07 | 已完成；后续简化为单次开始、后端生成 ID、单一 status 和集中测试记录 | [测试生命周期](../test-cancellation-lifecycle.md) |
| [13 冲突与调用快照](13-config-conflicts-call-snapshot.md) | 03、05、07 | 已完成；后续清理失败改为日志及下次重试 | [配置冲突](../config-conflicts-call-snapshot.md) |
| [14 稳定 ID 与消费者复用](14-stable-id-consumer-reuse.md) | 13 | 已完成；后续加入同步调用，工具库迁入 tools | [复用接口](../stable-id-consumer-reuse.md)、[模块布局](../tool-module-layout.md) |

## 票据之后的修订

`c42a50f` 增加同步 `invoke()`、跨循环桥接、关闭／取消清理及同步脚本入口，并将工具库迁入 `tools`。同步和异步入口目前都在 `shikigen.tools.tool_library`，循环桥接在 `shikigen.tools.tool_calls`；旧 runtime 路径已移除。

票据保留原验收清单和当时的状态文字，文件开头给出当前指南入口。延期凭据目标、阶段性未支持项和旧测试计数都按日期阅读；后续开发依据各主题的最新记录与实际代码确定回归范围。
