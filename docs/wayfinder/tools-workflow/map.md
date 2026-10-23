---
id: tools-workflow
title: 可复用工具库与适配器首版决策地图
labels: ["wayfinder:map"]
status: closed
assignee: codex
---

# 可复用工具库与适配器首版决策地图

## Destination

调查主流 Agent 框架和应用的工具定义、连接与执行配置，明确本项目 MCP、Python 代码、HTTP 请求工具的首版录入项、适配器边界、创建编辑删除与测试行为，以及未来工作流和定制 Agent 的复用契约。
终点是经过用户确认、足以开始开发的简明方案；本轮先调查和规划，随后开发，不实现应用代码。

2026-10-13 已到达规划终点：五项子决策全部确认，开发前的已知问题已决定，规划票据均已关闭。本地图保留当时的规划范围。

2026-10-23：应用实现及后续修订已形成[开发指南](README.md)、[14 票实施索引](implementation/index.md)和[验证入口](validation.md)。下文“现状”与“本轮不实现”描述规划阶段，当前开发先读上述入口及对应主题最新记录。

## Notes

- 用户于 2026-10-12 确认：学习阶段，保持简单；本轮调查和规划。首版只支持 Python 代码片段；先完成工具管理、手动测试及未来复用接口，完整工作流编辑器、定制 Agent 页面和接入当前聊天 Agent 不在本轮范围。
- 用户确认 MCP 为“连接服务后自动发现并勾选工具”，包含本地 stdio 与远程 Streamable HTTP。服务连接和单个可调用工具是两个层次。
- 参数来源与结果保留见已关闭的执行决策；按类型的表格/高级编辑及 Python 只读预览边界见已关闭的页面决策，不要求复杂输出映射。
- HTTP 首版需要 OpenAPI 导入；导入从文档生成可调用工具，运行时按单个 HTTP 接口执行。导入、执行及页面保存边界已分别定稿。
- 领域用语沿用 [CONTEXT.md](../../../CONTEXT.md)，新定义按[领域文档约定](../../agents/domain.md)维护；决策使用 grilling 与 domain-modeling，外部事实使用 research。
- 当前基础见[现状调查](baseline.md)：Python harness、LangChain BaseTool、ToolRegistry 和 MCP loader 可复用；尚无工具管理页面、工具定义存储或 CRUD API。
- 页面沿用[设计规范](../../../frontend/design.md)中的全局应用栏、主导航、冷灰侧栏与靛蓝操作色；聊天工具调用记录不充当工具定义。后续 ticket 涉及工具页时，开发与验收先读取[工具页面原型与参照规则](../../../frontend/design.md#工具页面原型)。
- 规格发布后用户明确采用 shadcn/ui、rjsf、AI Elements；工具表单按 schema 用 rjsf 动态渲染，具体分工与既有参数编辑边界已补入[页面决议](tickets/004-management-ui-lifecycle.resolution.md)。
- 追踪方式见[本地 tracker](tracker.md)。research 子代理可以完成调查；其他子票据通过用户实际参与逐项解决，每次最多解决一项非 research 决策。

## Decisions so far

<!-- 只索引已关闭票据；用户的建图范围确认记录在 Notes。 -->

- [调查主流 Agent 的工具录入项与发现机制](tickets/001-mainstream-tool-fields.md)：区分调用定义、类型配置与产品管理字段；MCP 自动发现、OpenAPI 导入生成 HTTP 工具，首版字段建议及来源已保存。
- [确定工具定义、适配器与稳定引用契约](tickets/002-definition-adapters-references.md)：公共定义基类加类型专属子类，代码登记适配器接入现有 Registry，按稳定 ID 引用最新定义；字段、MCP 来源身份、名称及复用入口已确认。
- [确定 OpenAPI 导入的首版范围](tickets/005-openapi-import-scope.md)：上传/粘贴常用子集，手工创建与导入共用 HTTP 定义；分别读取地址、名称和参数，预览诊断后保存，可编辑且再次导入不覆盖。
- [确定 MCP、Python 与 HTTP 的执行和测试边界](tickets/003-execution-test-contract.md)：Python 固定 main 并自动解析入参，三类工具共用结构化输入输出及直接执行入口；配置文件/外置代码、凭据、超时和会话扩展边界已确认。
- [确定工具管理页面与增删改生效规则](tickets/004-management-ui-lifecycle.md)：扩展下分别管理工具与 MCP 服务，Python 参数预览加未知类型补齐；草稿、测试、发现更新、文件保存和删除生效规则已确认。

## Not yet specified

没有已知的开发前必需决策。实际 MCP 服务与用户常用 OpenAPI 文档样例在开发中按已确认范围验证和诊断；需要超出该范围的适配时，依据真实样例另行规划。

## Out of scope

- 本轮应用实现、应用代码提交、部署与安装包分发；本地图用于调查及逐项确认开发方案，研究分支按 wayfinder 单独保存。
- 完整工作流编辑器、定制 Agent 管理页面及自动挂载到当前聊天 Agent；本模块应留下后续引用入口。
- 技能管理实现；本轮只确定扩展导航中的预留位置，后续单独规划 Skill 能力。
- JavaScript 等其他代码运行时、工具市场、团队协作、多租户、计费、复杂权限系统和版本发布平台。
- 本轮不建设生产级代码沙箱；首版执行边界与超时见已关闭决策，不能把本机子进程称为安全沙箱。

