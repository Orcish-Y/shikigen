# 子 Agent 委派：task tool

实现了 `task(description, agent_type)` 工具，允许 Lead Agent 将子任务委派给独立的后台子 Agent。

**架构**：
- `build_task_tool(model, tool_registry)` — 闭包工厂，捕获 model 和工具注册表
- `_create_subagent(agent_type)` — 用 `create_agent()` 创建子 agent，工具按类型过滤
- `sub_agent.ainvoke(...)` — Lead Agent 同步等待子 agent 完成，
  并取回最后一条消息的纯文本

**两种子 Agent 类型**：
- `general` — 全量工具（9 个），用于复杂任务
- `bash` — 仅 shell/文件工具（5 个），用于代码/命令任务

**对比 deer-flow**：
- deer-flow 用 `SubagentExecutor`（线程池 + Future + SSE 事件）支持真正并行
- 我们先保留简单的 fork-join 语义：Lead Agent 等待 task 完成，
  暂不转发子 agent 中间事件，也不提供后台 Future 管理

**Evidence**: `tools/task_tool.py`, `harness/agent.py` lines 27-28,
`tests/test_task_tool.py`

**Implications**: 项目核心功能完整了。下一步可选：Goal 续跑、多轮自动化、前端 UI。
