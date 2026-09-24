# 调查与技术参考

集中保存原 `docs/` 与 `learning-records/temp/` 中的调查资料，保留原有日期、来源与技术论证。
以下结论对应各自调查时点，本次归档未重新核验外部项目。当前采用的设计见[项目开发参考](../project.md)。

## 持久化与运行边界

- [Agent / Harness 的持久化职责归属](agent-persistence-ownership-research.md)
- [Run 与持久化边界对照](agent-runtime-boundary-comparison.md)
- [DeepSeek Harness 持久化](deepseek-harness-persistence-research.md)
- [消息状态与流式事件](agent-message-state-research.md)
- [Interrupt / Approval / Resume API](interrupt-resume-api-research.md)

## LangGraph 技术参考

- [标识机制：名称、标签、命名空间与 Run ID](langgraph-identifiers.md)
- [状态存储位置选择](runtime-context-and-storage-strategy.md)

## 子 Agent 与多会话

- [子 Agent 注册与运行时创建](01-subagent-construction-and-runtime.md)
- [多会话能力对照](02-multi-session-agent-landscape.md)
- [父子会话生命周期编排](03-child-session-lifecycle-control.md)

## MCP

- [DeerFlow MCP 配置](deerflow-mcp-config.md)
- [DeerFlow MCP 空值处理](deerflow-mcp-null-handling.md)
- [主流 Agent 的 MCP 启动延迟处理](mcp-startup-latency-mainstream-agents.md)

[返回文档导航](../README.md)
