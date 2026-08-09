# Goal 续跑：Middleware 方案

用户实现了 Goal 续跑功能，选择了 middleware 方案而非 loop 修改——比初始提议的耦合更低。

**核心设计**：
- `GoalMiddleware(AgentMiddleware[GoalAgentState])` — 完整的 goal 逻辑封装在 middleware 中
- `GoalAgentState` 扩展 `AgentState`，通过 `state_schema` 自动合并进 agent state + 随 checkpoint 持久化
- `before_agent` 检测 `/goal` 前缀消息，初始化 goal 状态机
- `aafter_agent` + `@hook_config(can_jump_to=["model"])` — 每轮结束后评估，未完成则注入续跑消息 + `jump_to: "model"` 让 LangGraph 回到 model node 继续
- `GoalEvaluator` — 纯 LLM 调用（`model.ainvoke(prompt)`），无工具、无 middleware

**状态机**：`inactive → running → satisfied | exhausted`

**关键优势 vs loop 方案**：
- `loop.py` 和 `main.py` 零修改——goal 功能的添加/删除只需在 `agent.py` 中加/删一行 middleware
- `state_schema` 让 goal 状态随 checkpoint 自动持久化
- `jump_to: "model"` 复用 LangGraph 原生控制流，不需要手动重新调用 `_stream_once`

**Evidence**: `middleware/goal_middleware.py` (186 行), `harness/agent.py` line 35

**Implications**: 用户对 LangGraph 的 middleware 协议（`state_schema`、`hook_config`、`jump_to`）有深层理解。项目功能完整——从 Agent Loop 到 Runtime 基础设施到 Goal 续跑全部覆盖。下一步可选：Web UI、社区工具集成、性能优化。
