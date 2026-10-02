# 子 Agent、多会话与生命周期编排

合并原 01～03 三份调查，基线日期 2026-08-05；能力结论仅对应原调查时点，本次未重新验证外部实现。全部源码链接、版本限制与控制矩阵在 [归档原文](../archive/README.md)。

## 三层接口不要混在一起

| 层次 | 做什么 | 为什么 | API 方向 |
| --- | --- | --- | --- |
| 构建期注册 | 声明可用 Agent、模型、工具和继承规则 | 稳定能力与配置边界 | registry、Agent spec、factory |
| 模型可见工具 | 暴露独立 worker 工具或统一分发工具 | 模型只理解实际 tool schema | `research(...)` 或 `task(agent_name, description)` |
| 运行时执行 | 创建调用或可寻址 child，跟踪结果和取消 | 决定独立身份、历史和生命周期 | invoke/spawn、status/wait、steer/cancel |

LangChain 的基础模式是 agent-as-tool：先 `create_agent()` 建 worker，再由工具调用它；`create_agent` 不会自动创建 subagent registry。Deep Agents 用 `subagents` 声明和 SubAgentMiddleware 标准化注册，并暴露统一 `task` 工具。一次独立 context 调用不自动成为持久会话。

## 判断多会话能力的口径

- 用户多会话：顶层上下文能创建、列出、切换、恢复。
- 父子会话：child 有稳定 ID、父子关系，可单独寻址和观察。
- 后台任务：调用返回后继续执行，并可稍后查询或恢复；父工具一直等待的线程执行不算。
- 隔离 invocation：拥有干净上下文但只返回一次结果，不保证能继续对话。
- 跨重启恢复：进程/服务重启后仍能恢复；页面离开而后端继续运行不算。

还须区分模型可调用的 in-band 控制工具与 UI/CLI/HTTP/SDK 的 external 控制面。

## 历史调查中值得保留的对照

| 样本 | 控制与身份 | 恢复边界 |
| --- | --- | --- |
| OpenClaw | `sessions_spawn` 返回 runId / childSessionKey，yield/status/cancel 与完成 push；native child 不提供父 LLM 任意 steer | 有限 orphan recovery；不能当作无条件恢复承诺 |
| Hermes | `delegate_task` 运行独立 AIAgent，聚合完成；运行期 child 与永久 session 不等同 | active run 不保证跨进程恢复 |
| DeerFlow | 同步 `task` 主要是隔离 invocation | 不等于持久 child session |
| Codex | 独立 Agent thread，模型控制创建、追加输入、等待与关闭 | 原调查未得到本地 child 跨进程恢复承诺 |
| Claude Code | subagent 与团队模型需分别判断；存在观察和追加指令能力 | 同 session 恢复与 in-process teams 不同 |
| Deep Agents Async | 将 Agent Server 的 thread/run API 包成模型控制工具 | 持久能力依赖服务端；同步 task 不具有同样语义 |
| 裸 LangGraph Agent Server | external Thread/Run API 可完整 | 不会自动成为主 LLM 可调用工具 |

DeepSeek Harness 未纳入原 2026-08-05 多会话矩阵；相关持久化证据见 [运行边界摘要](persistence-and-runtime.md)。这不代表本次已经补查其 child 控制能力。

## 对本项目后续开发的材料入口

目前 `task` 等待子 Agent 返回。要演进为后台 child，应先定义稳定身份、父子归属、历史与结果交付、并发配额、取消传播、steer 的语义和恢复意图，再决定工具 schema；无需为 agent-as-tool 本身引入完整 session manager。共享文件系统与 OS 隔离也不能从“上下文隔离”推导出来。

当前规划见 [项目后续扩展](../project.md#后续扩展)，教学实现过程见 [子 Agent 学习记录](../../learning-records/0015-subagent-task-tool.md)。

## 原始来源

- [LangChain Subagents](https://docs.langchain.com/oss/python/langchain/multi-agent/subagents)
- [OpenClaw Sub-agents](https://docs.openclaw.ai/tools/subagents)
- [Codex App Server 原始接口资料](https://github.com/openai/codex/blob/main/codex-rs/app-server/README.md#items)
- [Hermes 官方仓库](https://github.com/NousResearch/hermes-agent)

归档 `research-originals.zip` 中的原路径：`docs/research/01-subagent-construction-and-runtime.md`、`02-multi-session-agent-landscape.md`、`03-child-session-lifecycle-control.md`。这些原文保留逐项一手证据和未确认限制。
