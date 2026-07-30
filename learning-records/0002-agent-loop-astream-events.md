# Agent Loop 核心概念：create_agent + astream_events

用户通过独立实现 `main.py`（异步版）和 `sync_agent.py`（同步版），演示了对 Agent Loop 核心概念的理解：

- `create_agent(model, tools, system_prompt)` 是 agent 工厂——返回编译好的 LangGraph StateGraph
- `agent.astream_events(input, version="v3")` 启动执行循环：LLM 决策 → 解析 tool_calls → 执行工具函数 → 把结果作为 ToolMessage 喂回 LLM → 循环直到 LLM 产出纯文本
- 消息历史通过 `values` 频道返回的完整 `messages` 列表来维护：`messages[:] = value["messages"]`
- 工具用 `@tool` 装饰器定义，docstring 自动生成为 LLM 可见的 function schema
- 实现了优雅退出（/exit, /quit, Ctrl+C）和 surrogate 字符安全处理

**Evidence**: `main.py` 和 `sync_agent.py` 均可运行，agent 正确调用 `add` 和 `get_current_time` 工具。

**Implications**: 第一阶段的核心概念已掌握。可以进入工具注册中心（ToolRegistry）、Middleware 链等架构层面的学习。
