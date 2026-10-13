---
id: tools-management-ui
title: 确定工具管理页面与增删改生效规则
parent: tools-workflow
labels: ["wayfinder:grilling"]
mode: HITL
status: closed
assignee: codex
blocked_by: [tools-definition-adapters, tools-openapi-import, tools-execution-tests]
resolution: 004-management-ui-lifecycle.resolution.md
---

# 确定工具管理页面与增删改生效规则

## Question

沿用现有工作台样式，工具列表、按类型创建/编辑表单、MCP 服务及发现工具的展示、输入参数表格与 JSON Schema 高级编辑、手动测试和删除确认如何组织？页面和后端需要哪些最小 CRUD / discovery / test 契约？

依赖：[确定工具定义、适配器与稳定引用契约](002-definition-adapters-references.md)、[确定 OpenAPI 导入的首版范围](005-openapi-import-scope.md)、[确定 MCP、Python 与 HTTP 的执行和测试边界](003-execution-test-contract.md)。

工具字段、名称和 MCP 编辑边界见[定义、适配器与引用决议](002-definition-adapters-references.resolution.md)；本票据据此明确页面与生命周期规则。

本轮页面与文件修改检测的现状见[工具管理接缝调查](../management-ui-baseline.md)。调查只记录可复用能力和缺口，下面的页面与生命周期选择仍通过用户实际参与确定。

原始提问及逐轮反馈见[讨论记录](../management-ui-discussion.md)，最终答案见[页面与生命周期决议](004-management-ui-lifecycle.resolution.md)。用户已确认两轮完整规则，本票据完成规划。

HTTP 手工创建、文档上传/粘贴、勾选接口、预览诊断、导入后编辑与再次导入的规则见[OpenAPI 导入范围决议](005-openapi-import-scope.resolution.md)；本票据将这些已确认行为组织为页面，并明确通用编辑与保存生命周期。

[执行与测试边界决议](003-execution-test-contract.resolution.md)已确认工具库写入项目 `config.json` 的 tool_library 分组，Python 源码放在配置文件旁的 `config/tools/` 并以相对路径引用。此票据还需明确配置与代码文件保存/删除的一致性、其他配置保留、外部文件修改后的读取时点与诊断；沿用已确认的执行字段、路径和密钥隐藏规则，不预设 SQLite 工具存储。

页面还需展示可选的输出 schema 和真实测试结果，明确哪些输出结构可提供字段提示、哪些缺少已知结构；如何编辑/查看这些信息按类型权限决定。三类工具的统一 inputs/data、非 LLM 复用入口、草稿测试、结果与超时规则沿用执行决议；本票据不设计 React Flow 连线或工作流映射编辑器。

用户明确要求 Python 主入口固定为 main，参数保留具名形式；页面需提供 main 模板、对应参数表及绑定诊断，不再提供入口函数名称配置或选择，也不通过自动执行用户代码来填充表单。

用户确认从源码自动解析入参、未知类型再补充；页面需组织“源码解析 → 定位 main → 展示自动参数及需补信息”，并明确源码修改后重新解析与原 schema 编辑的同步行为。支持的签名、注解和未知类型规则沿用执行决议，不提前把所有源码都当作可完整自动推断。

用户在本轮补充：主导航以“扩展”等总入口容纳工具、MCP 与 Skill；Python 参数表仅预览源码确定的属性，未知类型通过下拉补齐。用户随后接受第二轮推荐，具体导航分层、参数补充和生命周期规则已在最终决议中定稿。

需要用户决定的边界：启用与可用状态如何分别显示，表单和高级 schema 是否可无损切换，未保存编辑如何处理，连接失败是否可保存，删除 MCP 连接对旗下工具的影响，工具被未来工作流/Agent 引用后的删除语义，以及修改配置何时作用于已经开始的调用。形成可交给用户实施的页面行为和验收场景，不设计全量工作流页面。

