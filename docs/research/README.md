# 调查与技术参考

原调查合并为三个主题。这里浓缩历史证据，不重新核验上游；使用具体 API 前按所用版本复核。已经采用的项目契约见 [project.md](../project.md)，完整原文、调查日期及全部来源保留在 [归档](../archive/README.md)。

| 主题 | 入口 | 适用开发问题 |
| --- | --- | --- |
| 持久化与运行边界 | [persistence-and-runtime.md](persistence-and-runtime.md) | checkpoint、消息事实、run 协调、审批恢复、SSE 重连由谁负责 |
| 子 Agent 与多会话 | [subagents-and-sessions.md](subagents-and-sessions.md) | agent-as-tool、独立 child 身份、控制工具、后台执行和跨重启恢复 |
| MCP 配置与启动 | [mcp.md](mcp.md) | 配置校验、工具发现、启动延迟、稳定工具快照和失败隔离 |
| 沙箱与工具执行隔离 | [sandbox-and-execution-isolation.md](sandbox-and-execution-isolation.md) | 控制面与执行面分离、Docker/OS 沙箱、多租户边界与命令爆炸半径控制 |

以下是开发指导与机制依据，保留原文：

- [LangGraph 标识：run_name / tags / metadata / namespace / run_id](langgraph-identifiers.md)
- [状态存储：State / Runtime Context / Messages / Middleware / Store / 外部缓存](runtime-context-and-storage-strategy.md)
- [Windows 托管与数据独占机制](windows-backend-lifecycle-mechanisms.md)

## 新增调查

- [Python 源码编辑与前端静态分析](python-editor-static-analysis.md)（2026-10-15）：比较 CodeMirror／Lezer、Monaco／Pyright、Pyodide 和 Tree-sitter，附隔离样例与存储测量。CodeMirror 6 + Lezer 已采用，后端保留权威复核；现行能力见[工具库指南](../wayfinder/tools-workflow/README.md)。

- [工具配置字段与适配器调查](tool-configuration-fields.md)（2026-10-12）：对照 LangChain、Dify、AutoGen、Claude Code 与 MCP/OpenAPI，区分共有定义、连接配置、自动发现与导入字段。原始产品取舍见[规划地图](../wayfinder/tools-workflow/map.md)，当前实现及范围调整见[工具库指南](../wayfinder/tools-workflow/README.md)。

[返回文档导航](../README.md)
