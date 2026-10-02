# 调查与技术参考

原调查合并为三个主题。这里浓缩历史证据，不重新核验上游；使用具体 API 前按所用版本复核。已经采用的项目契约见 [project.md](../project.md)，完整原文、调查日期及全部来源保留在 [归档](../archive/README.md)。

| 主题 | 入口 | 适用开发问题 |
| --- | --- | --- |
| 持久化与运行边界 | [persistence-and-runtime.md](persistence-and-runtime.md) | checkpoint、消息事实、run 协调、审批恢复、SSE 重连由谁负责 |
| 子 Agent 与多会话 | [subagents-and-sessions.md](subagents-and-sessions.md) | agent-as-tool、独立 child 身份、控制工具、后台执行和跨重启恢复 |
| MCP 配置与启动 | [mcp.md](mcp.md) | 配置校验、工具发现、启动延迟、稳定工具快照和失败隔离 |

以下是开发指导与机制依据，保留原文：

- [LangGraph 标识：run_name / tags / metadata / namespace / run_id](langgraph-identifiers.md)
- [状态存储：State / Runtime Context / Messages / Middleware / Store / 外部缓存](runtime-context-and-storage-strategy.md)
- [Windows 托管与数据独占机制](windows-backend-lifecycle-mechanisms.md)

[返回文档导航](../README.md)
