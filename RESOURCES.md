# AI Agent Harness 学习资源

## Knowledge

- [LangChain Agents 文档](https://docs.langchain.com/oss/python/langchain/agents)
  `create_agent`, middleware, stream modes 的权威参考。目前最直接相关的文档。

- [LangGraph 文档](https://langchain-ai.github.io/langgraph/)
  Agent 底层的 graph 执行引擎。理解 checkpoint、streaming、interrupt 机制时需要。

- [deer-flow 源码](~/code/deer-flow)
  生产级 Agent 系统的完整实现。用于对照学习——不要求读懂全部，作为"参考答案"。

- [LangChain `@tool` 文档](https://docs.langchain.com/oss/python/langchain/tools)
  工具定义、参数 schema 自动生成、ToolRuntime 的说明。

## Wisdom (Communities)

- [LangChain Discord](https://discord.gg/langchain)
  遇到 LangChain/LangGraph bug 或 API 问题时最有用的地方。

## Gaps
- 缺少一本系统讲解 Agent 架构设计的书或长文（目前靠 deer-flow 源码逆向学习）
- 缺少中文社区的高质量 Agent 工程讨论
