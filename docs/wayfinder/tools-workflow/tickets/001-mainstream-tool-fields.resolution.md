# 调查主流 Agent 的工具录入项与发现机制：决议

解决日期：2026-10-12。AFK 研究由 research 子代理完成，主代理核对报告、项目锁定版本与关键官方来源。

## Resolution

答案及完整出处保存在[工具配置字段与适配器调查](../../../research/tool-configuration-fields.md)。研究覆盖 LangChain、Dify、AutoGen、Claude Code，以及 MCP 和 OpenAPI 官方规范；它们分别是框架、应用、客户端和协议，不将其配置混称为通用标准。

调查明确了共有调用定义与类型执行配置的区别：MCP 自动发现单个工具的定义，用户录入服务连接并勾选；Python 需要代码、输入与入口约定；OpenAPI 可以生成单接口 HTTP 工具，服务地址与认证信息仍需要确认。产品稳定 ID、启用状态、CRUD 和更新生效规则属于本项目后续决策，报告中的取舍均标为建议。

研究中发现的校验和兼容边界已纳入后续问题：字典 schema 不自动得到 BaseTool 的完整 JSON Schema 校验；复杂参数不能因四列表格丢失约束；MCP 多内容块与附加数据、OpenAPI 版本/引用/认证必须明确支持范围。未升级依赖或执行兼容测试。

## 研究资产与保存范围

- [独立研究分支中的报告](https://github.com/Orcish-Y/shikigen/blob/research/tool-configuration-fields-20261012/docs/research/tool-configuration-fields.md)已推送，提交为 `896e4bc216d7d4419b6cc114cb59188ff56c8a04`。
- 分支只新增一个报告文件，无 PR、无合并；当前工作分支和真实 Git 索引保持原状。报告的地图与现状调查回链在当前本地工作区存在，不包含在仅保存研究文件的远端分支中。
- 本轮仅文档/源码调查；未连接 MCP、执行代码工具或验证页面/API。票据关闭表示调查完成，不表示首版设计已确认或产品已实现。

## 后续上下文

下一项是[确定工具定义、适配器与稳定引用契约](002-definition-adapters-references.md)。之后依次确认[OpenAPI 导入范围](005-openapi-import-scope.md)、[执行和测试边界](003-execution-test-contract.md)、[工具管理页面与增删改生效规则](004-management-ui-lifecycle.md)。这些 HITL 票据保持开放。

