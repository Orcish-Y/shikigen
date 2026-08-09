# Subagent：注册、模型工具与运行时创建

> 调研日期：2026-08-05。仅采用官方文档与官方 GitHub 源码。以下结论特意区分三个层次：**构建期注册**（程序启动时知道有哪些 agent）、**模型可见工具**（LLM 实际能调用什么名字）、**运行时 spawn/invoke**（一次调用究竟创建了什么）。

## 结论先行

1. **LangChain `create_agent` 的 subagent 模式确实是通过 tools 组合的，但不是 `create_agent` 自动识别“这是 subagent”。** 普通 LangChain 的官方做法是先用 `create_agent` 建好 worker，再把 `worker.invoke(...)` 包装成 `@tool`，最后把这个 tool 放进 supervisor 的 `tools=[...]`。`create_agent` 自身没有 `subagents` / `subagent_list` 参数。
2. **Deep Agents 当前参数准确名称是 `subagents`，不是 `subagent_list`。** Python 是 `create_deep_agent(..., subagents=[...])`；JavaScript 是 `createDeepAgent({ subagents: [...] })`。Deep Agents 用 `SubAgentMiddleware` 把声明式 spec 或预编译 runnable 注册起来，并自动向主模型暴露统一的 `task` tool。
3. 两者的底层思想没有冲突：**Deep Agents 本质上是对“agent-as-tool”模式的标准化封装**。区别主要在是否由框架负责 registry、统一 tool schema、上下文裁剪、结果回填、默认 agent、继承规则、追踪和同步/异步生命周期。

## 一、LangChain `create_agent`：手写 agent-as-tool

### 三层拆解

| 层次 | 实际发生的事 |
|---|---|
| 构建期注册 | 开发者先调用 `create_agent(...)` 创建 worker runnable，再写一个调用它的 tool；不存在内建 subagent registry。 |
| 模型可见工具 | 主模型只看到你传入 `tools` 的 tool schema，例如每个 worker 一个 `research` tool，或开发者自己实现的单一 `task(agent_name, description)` dispatch tool。 |
| 运行时 | 模型调用 tool；tool 函数内部执行 `subagent.invoke(...)`，将 worker 的最终消息作为 tool result 返回。是否同步、传哪些上下文、返回哪些 state，全由 tool 实现决定。 |

LangChain 官方文档明确说 supervisor “calls subagents as tools”，并给出完整代码：先创建 `subagent = create_agent(...)`，再包装 `call_research_agent`，最后 `main_agent = create_agent(..., tools=[call_research_agent])`。[LangChain：Subagents，Basic implementation](https://docs.langchain.com/oss/python/langchain/multi-agent/subagents#basic-implementation)

官方还给出两种 model-visible surface：

- **tool per agent**：每个 worker 一个独立工具名，输入输出最容易定制。
- **single dispatch tool**：自己维护 `SUBAGENTS` registry，只向模型暴露统一的 `task(agent_name, description)`。[LangChain：Tool patterns](https://docs.langchain.com/oss/python/langchain/multi-agent/subagents#tool-patterns)

因此，“LangChain 现在使用 tools 引入 subagent”是对的；更精确的说法是：**LangChain 把 subagent 当作一种多 agent 架构模式，而 `create_agent` 只负责创建普通 agent。开发者通过 tool composition 把一个 agent 暴露给另一个 agent。**

## 二、Deep Agents：声明式 `subagents` + 自动生成 `task`

### 参数名称

当前 Python 签名是：

```python
create_deep_agent(
    model=...,
    tools=...,
    *,
    subagents: Sequence[SubAgent | CompiledSubAgent | AsyncSubAgent] | None = None,
    ...,
)
```

官方源码签名见 [`graph.py`](https://github.com/langchain-ai/deepagents/blob/main/libs/deepagents/deepagents/graph.py#L366)。官方 API reference 也使用 `subagents`。[Python `create_deep_agent` reference](https://reference.langchain.com/python/deepagents/graph/create_deep_agent)

JavaScript 对应为 `createDeepAgent({ subagents: [...] })`，字段仍叫 `subagents`。[Deep Agents JS：Subagents](https://docs.langchain.com/oss/javascript/deepagents/subagents)

在当前官方代码和文档中没有 `subagent_list` 这个公开参数；若看到这个名字，更可能是示例里的本地变量、旧分支或第三方封装。

### `subagents` 能放什么

- `SubAgent`：声明式字典/spec，核心字段是 `name`、`description`、`system_prompt`，可覆盖 `tools`、`model`、`middleware`、`skills`、`permissions`、`response_format` 等。
- `CompiledSubAgent`：已经构建好的 LangChain agent 或 LangGraph runnable，以 `runnable` 传入。
- `AsyncSubAgent`：指向已部署 graph 的后台 agent spec；由独立的 `AsyncSubAgentMiddleware` 处理。

详见 [Deep Agents：Subagent configuration](https://docs.langchain.com/oss/python/deepagents/subagents#configuration) 与 [`create_deep_agent` 源码参数说明](https://github.com/langchain-ai/deepagents/blob/main/libs/deepagents/deepagents/graph.py#L470-L508)。

### 三层拆解

| 层次 | 同步 `SubAgent` / `CompiledSubAgent` |
|---|---|
| 构建期注册 | `create_deep_agent` 把 specs 交给 `SubAgentMiddleware`；声明式 spec 会被编译为普通 LangChain `create_agent(...)` runnable，compiled runnable 则直接登记。默认还会补一个 `general-purpose`。 |
| 模型可见工具 | 模型不直接看到 N 个 agent tools，而是看到一个统一的 **`task`** tool；tool 描述中列出可用 agent 的 `name` 与 `description`。 |
| 运行时 | `task(description, subagent_type)` 从 registry 选择已编译 runnable，为本次调用构造新的 state，把 messages 重置成单条任务 `HumanMessage`，invoke worker，并只把结构化结果或最后一条非空 AI 消息放回父 agent。同步 subagent 期间父 agent 阻塞。 |

源码证据：

- `create_deep_agent` 条件性挂载 `SubAgentMiddleware`，并最终仍调用 LangChain `create_agent(...)` 构建主 agent：[`graph.py`](https://github.com/langchain-ai/deepagents/blob/main/libs/deepagents/deepagents/graph.py#L654-L675)、[`graph.py`](https://github.com/langchain-ai/deepagents/blob/main/libs/deepagents/deepagents/graph.py#L826-L849)。
- raw spec 最终也是通过 LangChain `create_agent(model, **create_agent_kwargs)` 编译：[`subagents.py`](https://github.com/langchain-ai/deepagents/blob/main/libs/deepagents/deepagents/middleware/subagents.py#L460-L500)。
- middleware 在构建 tool 时先编译 registry，并把 agent 名称/描述写入统一 tool description：[`subagents.py`](https://github.com/langchain-ai/deepagents/blob/main/libs/deepagents/deepagents/middleware/subagents.py#L581-L614)。
- `task` 调用时选择 runnable、创建独立消息 state、执行并将最终结果回填父 state：[`subagents.py`](https://github.com/langchain-ai/deepagents/blob/main/libs/deepagents/deepagents/middleware/subagents.py#L670-L760)。

### 和手写 subagent tool 的实际区别

| 维度 | LangChain 手写 tool | Deep Agents `subagents=` |
|---|---|---|
| 注册接口 | 无专用接口；自行保存 runnable/registry | 一等参数 `subagents` |
| 模型工具面 | 任意：每 agent 一个 tool，或自建 dispatcher | 同步 subagent 默认统一为 `task` |
| 上下文输入 | tool 作者完全决定 | 默认隔离 messages，只以任务描述启动，同时按规则传播部分 runtime state/context |
| 输出 | tool 作者完全决定 | 标准化为 structured response 或最后一条 AI message，并封装成 `ToolMessage` |
| 默认能力 | 无 | 默认 `general-purpose` subagent；中间件自动处理继承、权限、skills、追踪等 |
| 灵活性 | 最大，可定制 tool schema、持久会话、上下文变换和输出合并 | 约定更强、样板更少；特殊图可用 `CompiledSubAgent` 逃生舱 |
| “创建”含义 | worker 通常在构建期已编译；运行时只是 invoke，是否动态创建由手写代码决定 | 同步 spec 在构建期编译，运行时为每次 `task` 创建干净 invocation/state；它不是每次重新构造 agent 定义 |

一句话：`subagents=` 是 **build-time registration API**，`task` 是 **model-visible dispatch tool**，`task` 内部的 runnable invocation 才是 **runtime child run**。

## 三、OpenClaw、Hermes、DeerFlow 分别如何做

### OpenClaw

| 层次 | 行为 |
|---|---|
| 定义/注册 | agent 可在 OpenClaw 配置中存在，spawn 时可选择目标 `agentId`；subagent 的模型、并发、深度、tool policy 等由 `agents.defaults.subagents` / per-agent 配置控制。它不像 Deep Agents 那样要求把一组 runnable 传给构造函数。 |
| 模型可见工具 | **`sessions_spawn`** 启动；**`sessions_yield`** 等待未来完成事件；**`subagents`** 用于查看/取消。有效工具是否出现取决于 profile 和 allow/deny policy。 |
| 运行时创建 | `sessions_spawn` 创建独立 child session，key 形如 `agent:<agentId>:subagent:<uuid>`，在专用 `subagent` lane 后台运行并立即返回 run id。完成后以内部事件 announce 给 requester，而不是作为当前 tool call 的同步返回值。 |

生命周期与隔离：

- 默认 `context: "isolated"` 创建干净 transcript；`context: "fork"` 才复制 requester transcript。[OpenClaw：Context modes](https://docs.openclaw.ai/tools/subagents#context-modes)
- child 有独立 session 和 token usage；可选要求 sandbox，但“独立 session”不等于默认拥有独立 OS sandbox。[OpenClaw：Sub-agents overview](https://docs.openclaw.ai/tools/subagents)
- 默认非阻塞、push completion；需要结果时用 `sessions_yield`，不要轮询。[OpenClaw：Spawn behavior](https://docs.openclaw.ai/tools/subagents#spawn-behavior)
- `cleanup` 可选 `keep` / `delete`，还支持 thread-bound persistent `mode: "session"`；普通 run 则是后台 child run。[OpenClaw：`sessions_spawn`](https://docs.openclaw.ai/tools/subagents#tool-sessions_spawn)
- 工具权限先继承 profile/policy，再施加 subagent 限制；leaf 默认不能继续 spawn，配置 `maxSpawnDepth >= 2` 后 depth-1 orchestrator 才能拥有 spawn/管理工具。[OpenClaw：Tool policy](https://docs.openclaw.ai/tools/subagents#tool-policy)

所以 OpenClaw 的“创建子 agent”最准确叫 **spawn session/run**，而不是仅仅 invoke 一个构建期 runnable。

### Hermes Agent

| 层次 | 行为 |
|---|---|
| 定义/注册 | 没有 Deep Agents 式 `subagents=[named specs]` 必填注册表。Hermes 内建 delegation tool；调用时主要通过 `goal`、`context`，以及可选的角色、迭代上限等参数描述 child。模型/provider 主要通过 `delegation` 配置覆盖，否则继承 parent。 |
| 模型可见工具 | **`delegate_task`**。既支持单任务，也支持 `tasks=[...]` 一次并行委派多个任务。 |
| 运行时创建 | 每个任务真正创建一个新的 child `AIAgent` 实例、新 conversation 和自己的 terminal session；child 只从 `goal` 与 `context` 获得任务上下文，最后 summary 回到 parent。 |

生命周期与隔离：

- 最新官方文档说明，顶层 model-facing delegation 在支持后续投递的 session 中自动后台运行并立即返回 handle；无后续投递能力的无状态 request/response endpoint 会退回同步执行。orchestrator child 则会等待自己的 children，以便汇总。[Hermes：Subagent Delegation](https://hermes-agent.nousresearch.com/docs/user-guide/features/delegation/)
- `delegate_task` 不接受 model-facing `toolsets` 参数；child 继承 parent 已启用的 toolsets，再由运行时移除 leaf 不应拥有的 delegation、clarify、memory write 等能力。[Hermes：Inherited Tool Access](https://hermes-agent.nousresearch.com/docs/user-guide/features/delegation/#inherited-tool-access)
- leaf 默认不能再 delegate；`role="orchestrator"` 加上提高 `delegation.max_spawn_depth` 才能嵌套。[Hermes：Depth Limit and Nested Orchestration](https://hermes-agent.nousresearch.com/docs/user-guide/features/delegation/#depth-limit-and-nested-orchestration)
- conversation 与 terminal session 隔离，但 Docker backend 是 Hermes 进程级长存容器，文件/安装状态会跨 `/new`、`/reset` 与 subagent 共享；所以“独立 terminal session”不能理解成“一 child 一容器”。[Hermes：Tools & Toolsets](https://hermes-agent.nousresearch.com/docs/user-guide/features/tools/)
- 正在运行的 child 不具备跨进程恢复能力：进程重启后运行中 attempt 标记为 unknown；session close/reset 会中断 children。已完成但尚未投递的结果可以恢复投递。[Hermes：Lifetime and Durability](https://hermes-agent.nousresearch.com/docs/user-guide/features/delegation/#lifetime-and-durability)

因此 Hermes 的词义重点是 **delegation**：模型调用 `delegate_task`，运行时才 fork/spawn 新的 `AIAgent` 实例。

### DeerFlow 2.x

| 层次 | 行为 |
|---|---|
| 定义/注册 | registry 预置 `general-purpose` 与 `bash`；也可在 `config.yaml` 的 `subagents.custom_agents` 声明专用 agent，或把 App UI 创建的 custom agent 当 subagent。配置定义 prompt、tools、skills、model、turn/timeout。 |
| 模型可见工具 | 内建 native subagent 统一通过 **`task`** 调用。外部 ACP agent 不走 `task`，而是 **`invoke_acp_agent`**。 |
| 运行时创建 | `task(...)` 查 registry、应用 config override、创建一次新的 agent invocation，使用自己的 prompt/tools 跑到完成/timeout/max turns，再把最终输出作为 tool result 返回 Lead Agent。内部 executor 用后台线程池并发执行和轮询，但从 Lead Agent 的一次 tool call 语义看是 fork-join。 |

生命周期与隔离：

- 官方 `task` 示例当前参数是 `agent`、`task`、`context`；registry 中 built-in agent 默认 timeout 900 秒，`general-purpose` 160 turns、`bash` 80 turns。[DeerFlow：Subagents](https://deerflow.tech/en/docs/harness/subagents)
- 每次 invocation 有隔离的 LLM context，不会看到主 agent 或其他 subagent 的 conversation；官方并未把它描述为每个 subagent 一个独立 sandbox。DeerFlow 的 filesystem/sandbox 隔离边界是 **per thread**，因此不要把 context isolation 等同于 filesystem/process isolation。[DeerFlow README：Context Engineering](https://github.com/bytedance/deer-flow#context-engineering)、[DeerFlow backend architecture](https://github.com/bytedance/deer-flow/blob/main/backend/README.md#sandbox-system)
- Lead Agent 每轮默认最多并发 3 个 `task` call；超出的 tool calls 由 `SubagentLimitMiddleware` 截断。[DeerFlow：Concurrency limits](https://deerflow.tech/en/docs/harness/subagents#concurrency-limits)
- native child 不获得递归 `task` 工具；官方仓库架构说明 `general-purpose` 使用除 `task` 外的工具。[DeerFlow `backend/CLAUDE.md`](https://github.com/bytedance/deer-flow/blob/main/backend/CLAUDE.md#subagent-system-packagesharnessdeerflowsubagents)
- ACP agent 是另外一种生命周期：由 DeerFlow 管理的 child process，通过 ACP wire protocol 通信，模型调用名是 `invoke_acp_agent`。[DeerFlow：ACP agents](https://deerflow.tech/en/docs/harness/subagents#acp-agents-external-agents)

## 四、横向对照

| 系统 | 构建期/配置期登记 | 主模型看到的工具 | 调用时实际动作 | 默认返回方式 | 主要隔离边界 |
|---|---|---|---|---|---|
| LangChain `create_agent` | 开发者自行创建 worker + 包装 tool | 自定义 tool 名，或自建 `task` | tool 内 `worker.invoke` | 通常同步 tool result | 由开发者实现；官方范式是干净 worker context |
| Deep Agents | `create_deep_agent(subagents=...)` | `task` | invoke 已编译 runnable，生成干净 child state | 同步 subagent 默认阻塞并返回 ToolMessage；AsyncSubAgent 另走后台工具 | message/context 隔离；backend/权限按配置继承或覆盖 |
| OpenClaw | 全局/per-agent 配置与可选目标 agent | `sessions_spawn` | 创建 UUID child session + background run | 立即返回 run id，完成后 push/announce | 独立 session；sandbox 可选/继承 |
| Hermes | 内建 delegation 能力；通常无 named-spec registry | `delegate_task` | 每个 task 新建 child `AIAgent` | 支持投递的 session 中后台 handle + 后续消息；无状态 endpoint 同步 fallback | fresh conversation + terminal session；backend 容器/文件可共享 |
| DeerFlow | built-in registry + YAML/UI custom agents | `task`（ACP 为 `invoke_acp_agent`） | registry lookup 后创建一次 invocation，由 executor 运行 | native `task` 最终以 tool result fork-join | LLM context 隔离；sandbox/filesystem 是 per-thread |

## 命名建议

如果要在自己的 harness 中建模，建议不要用一个词覆盖三件事：

- `register_subagent(spec)`：构建期登记能力。
- `delegate_task(...)` 或模型工具 `task(...)`：模型表达业务意图。
- `spawn_subagent_run(...)`：运行时创建 child execution/session。

这样能避免把“把 runnable 放进 registry”“模型选择某个 worker”“系统真正创建一个隔离运行实例”混为一谈。
