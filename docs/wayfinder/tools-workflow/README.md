# 工具库开发指南

整理于 2026-10-23，当前代码基线为 `c42a50f`。HTTP、Python、MCP、OpenAPI 导入、草稿测试、配置冲突和稳定 ID 复用已有实现；工具实例支持同步与异步调用。14 张开发票的原文、完成范围及后续修订见[实施索引](implementation/index.md)。07 的 stdio 主链路已实现，原票中的统一凭据管理要求仍延期。

## 接手顺序

1. 先按下表找到本次修改的实现记录，确认当前行为和延期项；模块归属参照[工具模块布局](tool-module-layout.md)。
2. 涉及页面时，先读[工具页面原型规则](../../../frontend/design.md#工具页面原型)，再对照 [demo-工具.html](../../../design/demo-工具.html)。页面布局遵循原型，字段和内容按实际能力调整。
3. 从[实施索引](implementation/index.md)追溯原验收项，从[验证入口](validation.md)选择相关回归。原始 PRD、开发前调查和阶段报告保留各自日期含义。
4. 修改完成后更新对应主题记录；若改变已确认行为，写清新决定、受影响接口和验证范围，再更新本入口或实施索引。

## 按改动查资料

| 改什么 | 先读什么 | 重点 |
| --- | --- | --- |
| 模块位置、依赖和 Agent 接入 | [模块布局](tool-module-layout.md)、[稳定 ID 复用](stable-id-consumer-reuse.md) | `tools` 管理工具自身能力，`core` 注册和组装 Agent，`runtime` 协调 Agent／Run |
| HTTP 参数与 schema | [HTTP 参数](http-parameters.md) | schema 是类型与必填约束的来源；映射只表达请求位置及序列化 |
| HTTP 认证 | [认证现状](http-auth-credentials.md) | 直接值、组合绑定、目标冲突和 Bearer 前缀 |
| 草稿、保存和来源编辑权限 | [编辑与草稿](tool-edit-drafts.md)、[配置冲突与调用快照](config-conflicts-call-snapshot.md) | 本次草稿、保存提交点、详情重读、整批提交及最新配置 |
| Python 源码与表单 | [源码执行](python-tool-execution.md)、[schema 同步](python-schema-sync.md) | CodeMirror／Lezer 本地反馈，后端权威解析；源码确定属性与用户补充分开 |
| MCP 连接与执行 | [stdio](mcp-stdio-tools.md)、[Streamable HTTP](mcp-streamable-http.md) | 独立连接、每次调用会话、完整结果及清理 |
| MCP 重新发现与删除 | [发现生命周期](mcp-discovery-lifecycle.md) | 真实来源快照、选择性更新、保留 ID 和本地编辑、未发现项保留 |
| OpenAPI 导入 | [基础导入](openapi-basic-import.md)、[兼容与认证](openapi-compatibility-auth.md) | 导入生成 HTTP 工具，诊断支持子集，所选项整批保存 |
| 测试、取消与结果 | [测试生命周期](test-cancellation-lifecycle.md) | 后端生成测试 ID、单次开始、终态与资源清理、执行观察脱敏 |
| 同步脚本或后续工作流消费者 | [复用接口与同步入口](stable-id-consumer-reuse.md) | 按 ID 重新读取，完整结果，调用循环归属及关闭 |

## 后续开发需要保持的边界

| 主题 | 当前约定 | 详细依据 |
| --- | --- | --- |
| 定义与身份 | `AnyToolDefinition` 按 `kind` 判别；ID 稳定，调用名称由前端建议、后端校验 | [定义决议](tickets/002-definition-adapters-references.resolution.md)、[复用记录](stable-id-consumer-reuse.md) |
| 写入响应 | 创建返回 ID，更新／删除成功返回 204；保存成功但详情读取失败只重读详情；响应丢失显示不确定 | [保存与冲突](config-conflicts-call-snapshot.md) |
| 清理失败 | 后端记录日志，在后续配置提交和启动时重试；成功响应不返回清理 `warnings` | [清理与提交点](config-conflicts-call-snapshot.md#保存与提交点) |
| 认证与脱敏 | 配置仍直接编辑和读取真实值；执行观察遮盖已知认证值，统一 credential 管理仍延期 | [认证现状](http-auth-credentials.md)、[执行观察](test-cancellation-lifecycle.md#可展示结果的脱敏) |
| MCP 更新权限 | 普通编辑保护来源；发现应用由独立入口校对真实快照，按 `(connection_id, remote_name)` 更新所选来源 | [发现生命周期](mcp-discovery-lifecycle.md) |
| Python 草稿 | 使用本次提交的配置与源码；旧定义用于身份和权限等约束，本次源码随执行快照传递 | [源码执行](python-tool-execution.md)、[调用快照](config-conflicts-call-snapshot.md#本次调用内容) |
| 测试身份与状态 | 开始接口生成 ID 并启动；`status` 为 running 或四种终态；查询／取消使用返回的 ID | [公开测试 API](test-cancellation-lifecycle.md#公开测试-api) |
| 返回值 | 完整 `ToolResult` 保留类型和失败事实；`data_available` 区分真实 null 与未取得返回 | [结果与清理](test-cancellation-lifecycle.md#预算返回和清理) |
| 消费者资格 | 每次按 ID 读取最新保存定义；已取得的本次调用内容固定；普通调用检查启用，手工测试可测禁用工具 | [快照规则](config-conflicts-call-snapshot.md#本次调用内容)、[消费者复用](stable-id-consumer-reuse.md) |
| 同步调用 | `ToolInstance.invoke()` 与 `ainvoke()` 共用异步执行链路；普通脚本使用 `open_sync_tool_library()` | [同步入口](stable-id-consumer-reuse.md#同步调用) |

以上是后续修订后的入口摘要，详细契约只在对应主题维护。规划决议中的 `server_id` 已由实现中的 `connection_id` 取代；旧票中的登记测试、凭据隐藏和清理警告条款按对应主题的后续修订阅读。

## 仍需另行开发

- 统一凭据存储、管理读取与编辑协议；当前执行结果脱敏不等于凭据管理已经完成。
- Python `async def main`：[已有方案](python-async-main-plan.md)，目前工具源码入口仍为同步 `def main`。这与调用方可使用 `ainvoke()` 是两件事。
- 完整工作流编辑器、字段映射调度、定制 Agent 管理，以及当前聊天 Agent 自动挂载已保存工具。
- 持久测试历史、跨重启恢复、MCP 会话池、生产级代码沙箱及超出既定范围的 OpenAPI 兼容能力。

## 资料层次

- [实施索引](implementation/index.md)：14 张开发票、依赖及阶段完成记录；`tickets/` 中的 001–005 是规划决策票，两套编号分别阅读。
- [验证入口](validation.md)：当前可运行的检查方式，以及阶段结果和本地证据的定位方法。
- [规划地图](map.md)及 `tickets/*.resolution.md`：2026-10-12 至 13 的原始决策，后续修订见各主题记录。
- [历史规格与整理记录](../../archive/2026-10-23/tools-workflow/README.md)：原 PRD、发布索引、迁移说明及资料保留范围。
- [开发前现状](baseline.md)、[执行接缝](execution-baseline.md)、[管理页面接缝](management-ui-baseline.md)：调查时的代码基线，供理解演进原因。

`.scratch/tools-workflow/` 保留本机日志、截图、探针和旧路径入口。长期开发依据在本目录；新 checkout 不依赖本机 scratch 即可阅读规格、实现记录和验收结论。
