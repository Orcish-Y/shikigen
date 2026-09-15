# Agent / Harness 的持久化职责归属调查

调查日期：2026-09-14。来源为当日读取的官方文档；这些项目持续演进，API 名称和部署默认值应以所用版本为准。文中明确区分官方事实与架构推论。

## 先区分持久化对象与职责

判断 persistence 在 server 还是 agent 侧，至少要分别回答：保存什么、谁决定保存时机、谁执行读写、谁装配数据库后端。对话历史、执行 checkpoint、长期 memory、服务端的 run/thread 资源不必由同一层管理。

本次样本覆盖 LangGraph / LangSmith Agent Server、OpenAI Agents SDK、Claude Agent SDK、Pydantic AI、Letta，以及本地 deer-flow；后续补查 DeepSeek Harness、OpenClaw、Hermes，见文末。它们代表不同架构，并非市场占有率排名。这里的 agent 侧指执行 loop 的 harness/runtime，不是让 LLM 自己决定是否保存对话；server 需要区分 HTTP 接口层与包含 worker、数据库的整套后端服务。

## LangGraph 与 LangSmith Agent Server

| 场景 | 官方行为 | 关键 API / 接口 |
| --- | --- | --- |
| LangGraph OSS | Graph runtime 使用注入的 checkpointer 保存 graph state；可以独立于 HTTP server 使用 | `StateGraph.compile(checkpointer=...)`、`thread_id` |
| 存储后端 | 独立 saver 接口，有内存、SQLite、Postgres 等实现 | `BaseCheckpointSaver.put`、`put_writes`、`get_tuple`、`list` 及异步版本 |
| 跨线程长期数据 | 与 thread checkpoint 分开，使用 Store 接口 | `compile(store=...)`、`store.put(...)` |

官方将 checkpoint 用于多轮记忆、暂停恢复、时间旅行与容错；它保存的对象是 graph 执行状态，不仅是最终回复。[LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence)

托管部署中，Agent Server 在 runtime 自动注入 checkpointer 和 memory store。API server 处理请求、查询状态和转发流；queue worker 执行 graph 并写 checkpoint。服务资源（assistant、thread、run、cron）默认由 PostgreSQL 管理；checkpoint 与长期 Store 的后端可以配置替换。文档也提供单机与拆分 API/worker 的部署方式。[Agent Server 架构](https://docs.langchain.com/langsmith/agent-server)

**架构推论：**“Agent Server 托管 persistence”描述的是平台责任，并不意味着 HTTP handler 负责逐步保存 agent 状态。Checkpoint 的保存与恢复语义在执行 runtime，具体数据读写在 saver，部署入口负责装配后端。

## Pydantic AI：消息历史、Harness 快照与 Durable Execution

基础 Agent 提供 `message_history` 输入及 `new_messages()` 等结果 API。官方将消息存在哪里、何时加载、如何关联会话留给应用：读取 thread 历史，运行 Agent，再追加本次新消息。序列化可使用 `ModelMessagesTypeAdapter`，但序列化本身并不是执行恢复机制。[Messages and chat history](https://pydantic.dev/docs/ai/core-concepts/message-history/#persisting-sessions)

当前 Pydantic AI Harness 提供 `StepPersistence` capability，通过 `Agent(capabilities=[StepPersistence(store=...)])` 接入运行边界，记录事件、消息快照和工具效果账本；有内存、文件、SQLite、MongoDB 后端。`continue_run(store, run_id=...)` 读取快照，再将消息传入 `Agent.run(message_history=...)`。**官方明确这不是完整 graph-state checkpoint**：不恢复 capability 状态、graph-node 状态、重试计数或进行中的流，也不自动去重外部工具副作用。Harness 仍为 0.x，API 可能在小版本间变化。[Step Persistence](https://pydantic.dev/docs/ai/harness/step-persistence/)

Pydantic AI 也可以把 durable execution 委托给 Temporal 等执行引擎。Temporal 集成中，agent loop 位于 worker 执行的 workflow，模型请求、工具调用等成为 activities；Temporal Server 跟踪执行并持久化进度。Web endpoint 可以启动 workflow，但直接在普通 endpoint 中调用 `agent.run()` 不会因此获得 durable execution。[Temporal integration](https://pydantic.dev/docs/ai/capabilities/durable_execution/temporal/)

当前入口包括 `TemporalDurability` capability、`PydanticAIPlugin` 和 Temporal client 的 `execute_workflow(...)`。仅挂 capability 还不够，Agent 必须在 Temporal workflow 中运行；旧 `TemporalAgent` wrapper 已被标为弃用。[Temporal durable agent API](https://pydantic.dev/docs/ai/capabilities/durable_execution/temporal/#durable-agent)

**架构推论：**Pydantic AI 展示了三种不同层次：简单对话历史由应用自行读写；Harness capability 在 Agent 生命周期边界记录快照；强执行恢复可由外部 workflow runtime/server 承担。应先选恢复语义，再确定持久化模块的位置。

## OpenAI Agents SDK

SDK 的 Runner 可以通过 `Runner.run(..., session=...)` 自动读取会话历史，并保存本次运行产生的新消息。存储接口提供 `get_items()`、`add_items()`、`pop_item()`、`clear_session()`；SQLiteSession、SQLAlchemySession 等负责具体读写。`SQLiteSession` 默认使用内存，传入数据库文件路径才跨进程保留。也能使用 OpenAIConversationsSession，把历史存到 OpenAI 服务。[Sessions 官方文档](https://openai.github.io/openai-agents-python/sessions/)、[SQLiteSession 源码参考](https://openai.github.io/openai-agents-python/ref/memory/sqlite_session/)

**架构推论：**Session 模式由 Runner 驱动、独立存储适配器执行，不要求自建 HTTP server。远端存储也不改变这一调用分层。这里证明的是会话历史能力，不能仅凭 Session 推断具有任意中间步骤的崩溃恢复。

## Claude Agent SDK

SDK 自动将会话写入磁盘，内容包括用户输入、工具调用与结果、模型回复；`resume` 可以重新加载指定会话。对话恢复与文件系统快照是不同功能。[Sessions 官方文档](https://code.claude.com/docs/en/agent-sdk/sessions)

当前文档还提供外部 `SessionStore`：应用实现 `append` 和 `load`，SDK 在 query 中调用前者写入 transcript，恢复时调用后者。Python 与 TypeScript 接口细节应按所装版本核对。[外部 SessionStore](https://code.claude.com/docs/en/agent-sdk/session-storage)

**架构推论：**写入时机属于 SDK/harness；存哪里由默认文件实现或应用注入的 store 决定。即使将 store 接到数据库，也无需让 HTTP route 重新实现消息保存流程。

## Letta：部署位置与代码职责是两个问题

当前 Letta Agent SDK 区分 cloud、local、remote backend。cloud 将 agent state 保存在 Letta Cloud，即使工具运行在用户自己的机器上；local 将状态与执行保留在本机；remote 的状态位置由所连接 App Server 的 backend 决定。[Deployment 官方对照表](https://docs.letta.com/agent-sdk/deployment)

Agent memory 与 conversation history 跨 SDK connection 保留；可以通过 `resumeSession(conversationId)` 继续会话。但 SDK 不重放断线期间错过的事件，需要通过 `listMessages()` 或 `bootstrapState()` 对账。[Sessions and durability](https://docs.letta.com/agent-sdk/sessions)

**架构推论：**这是状态可由后端服务托管的实例，不能根据工具所在机器推断状态所在机器。当前 Docker 文档已属于 legacy/deprecated 路线，不应用旧版“Letta 一律是 Docker server + Postgres”描述所有当前部署。[旧 Docker 部署文档](https://docs.letta.com/v1-sdk/docker)

## 本地 deer-flow：具体目录与调用链

本节直接读取本地源码，HEAD 为 `244ce7739f13d44ce7ee5679eab114eb178f89f1`；未验证其等同于调查当天上游 main。

| 责任 | 源码位置与证据 |
| --- | --- |
| 生命周期与装配 | [gateway/deps.py](/home/orcish/code/deer-flow/backend/app/gateway/deps.py:348) 的 `langgraph_runtime()` 初始化 persistence engine、checkpointer、run/thread/event stores |
| 保存后端工厂 | [runtime/checkpointer/async_provider.py](/home/orcish/code/deer-flow/backend/packages/harness/deerflow/runtime/checkpointer/async_provider.py:168) 的 `make_checkpointer()` 管理 saver 生命周期 |
| 执行时接入 | [runtime/runs/worker.py](/home/orcish/code/deer-flow/backend/packages/harness/deerflow/runtime/runs/worker.py:703) 将 checkpointer/store 挂到执行 graph；同一文件有事件 store 的写入调用 |
| SQL 实现 | [persistence/engine.py](/home/orcish/code/deer-flow/backend/packages/harness/deerflow/persistence/engine.py)、[persistence/run/sql.py](/home/orcish/code/deer-flow/backend/packages/harness/deerflow/persistence/run/sql.py) 等位于 harness 包 |

**架构推论：**deer-flow 将不少服务持久化实现也收进 harness 包，但 HTTP gateway 仍承担装配职责。目录名不能单独证明概念归属，应一起看依赖方向与实际调用者。

## 对 shikigen 当前分层的意义（架构建议，非代码审查）

当前项目已经存在两条持久化路径：

- [checkpoint/provider.py](/home/orcish/code/shikigen-agent/packages/harness/shikigen/checkpoint/provider.py:13) 提供 checkpointer，agent 工厂接收它，用于 graph 执行状态。
- [app/persistence/chat_store.py](/home/orcish/code/shikigen-agent/app/persistence/chat_store.py:63) 保存产品的 threads、runs、run_events。
- [ChatPersistenceMiddleware](/home/orcish/code/shikigen-agent/packages/harness/shikigen/middleware/chat_persistence_middleware.py:59) 在消息形成的生命周期边界写 journal，依赖本文件中的 `MessageJournal` Protocol，不导入 app 的具体 ChatStore。
- [app/server.py](/home/orcish/code/shikigen-agent/app/server.py:19) 的 lifespan 创建并注入上述组件。

因此不需要因为其他项目把文件放在 harness，就把自己的整个 ChatStore 移过去。建议按数据语义划分：

| 做什么（What） | 为什么（Why） | 接口方向（How） |
| --- | --- | --- |
| Harness/runtime 驱动执行 checkpoint | runtime 知道执行边界和恢复位置；CLI、server 都需要 | 注入 `BaseCheckpointSaver`，不依赖 FastAPI Request |
| 在消息形成处记录完整消息 | runtime/middleware 能拿到完整结构；HTTP token 流不是完整执行状态 | 当前 `MessageJournal.append_event()` 即是一种 seam |
| App 保存用户、会话归属、产品 run 状态和查询投影 | 这些语义服务于产品与多用户管理 | 应用服务调用 ChatStore/repository；HTTP route 调用应用服务 |
| Server/CLI 入口管理存储生命周期 | 决定配置、连接与资源关闭的责任应有明确归属 | lifespan / async context manager 创建并注入后端 |

如果将来把持久 run 调度本身做成可复用 harness 能力，它的 RunStore 也可以下沉；不能仅因数据名叫 run 就认定它永远属于 server。反过来，SQL 实现留在 app，只要 harness 依赖抽象接口，也不构成层次倒置。

最后要分别定义三个能力：消息历史让下一轮有上下文；checkpoint/workflow history 支持执行恢复；事件日志让客户端补读已提交事实。三者可能共享数据库，也可能有重叠数据，但拥有其中一个不自动获得另外两个。本文未对当前实现做故障注入或一致性验证。

## 补查：Hermes（2026-09-14）

官方项目：[NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent)。本节依据当前官方开发者文档，未运行项目。

Hermes 的共享存储是 `SessionDB`，实现入口位于 `hermes_state.py` 及 `hermes_state_*.py`。默认文件为 `~/.hermes/state.db`，可由 `HERMES_HOME`/profile 改变；会话、消息、模型使用记录与 gateway 路由等存在 SQLite 中，旧的逐会话 JSONL 已被替代。接口包括 `create_session()`、`append_message()`、`get_messages_as_conversation()`。[Session Storage](https://hermes-agent.nousresearch.com/docs/developer-guide/session-storage)

正常消息写入由 agent 承担；官方特别说明 gateway 在 agent 已声明持久化归属时跳过 transcript 写入，异常补写也要先检查本次输入是否已保存。这并非普遍的 exactly-once 承诺。[写入归属说明](https://hermes-agent.nousresearch.com/docs/developer-guide/session-storage#codex-app-server-input-ownership)

Gateway 的 `gateway/session.py::SessionStore` 管理平台会话与 session key；GatewayRunner 解析路由、检查权限、创建 AIAgent、运行会话并向平台发送结果。API server 是其平台适配入口之一。[Gateway Internals](https://hermes-agent.nousresearch.com/docs/developer-guide/gateway-internals)

长期记忆另由 `~/.hermes/memories/MEMORY.md` 与 `USER.md` 承担，通过 `memory` 工具修改，在会话开始时加载。它们与自动保存的 SQLite transcript 是不同机制。[Persistent Memory](https://hermes-agent.nousresearch.com/docs/user-guide/features/memory)

**架构推论：**Hermes 是“agent 驱动正常 transcript 保存 + gateway 管理路由/交付 + 共享存储模块”的组合。不能说全部 persistence 都在 server，也不能说 gateway 完全不写数据。这里的证据支持消息恢复与会话连续性，未证明任意工具调用中途具有 graph checkpoint 式恢复。

## 补查：OpenClaw（2026-09-14）

官方项目：[openclaw/openclaw](https://github.com/openclaw/openclaw)。本节核对当日官方文档与 main 源码，未固定 commit，未运行项目。

Gateway 是 session 状态的权威：UI/TUI 查询 Gateway，远程模式下数据位于 Gateway 主机。当前 session metadata 和 transcript 均进入 per-agent SQLite，默认位置为 `~/.openclaw/agents/<agentId>/agent/openclaw-agent.sqlite`。metadata 负责 sessionKey、sessionId、活动时间等，transcript 保存消息、工具调用和压缩摘要。[Session 管理](https://docs.openclaw.ai/reference/session-management-compaction)、[磁盘存储](https://docs.openclaw.ai/reference/session-management-compaction/store)

执行调用链为 `agent RPC → agentCommand → runEmbeddedAgent`。RPC 负责校验、解析会话与保存 metadata；runtime 运行模型和工具并驱动 transcript 写入。开始 streaming 前持久化 `activeWriterRunId`，transcript 变更通过 `expectedWriterRunId` 检查写入归属。`tool_result_persist` 是工具结果写入前的同步 hook。[Agent loop](https://docs.openclaw.ai/concepts/agent-loop)

源码中 `src/auto-reply/reply/session.ts` 的 `initSessionState()` 通过 `runExclusiveSessionStoreWrite()` 协调会话初始化，存储队列由独立 `config/sessions/store-writer` 模块提供；这与“会话生命周期和存储实现分离”的判断一致。[会话初始化源码](https://github.com/openclaw/openclaw/blob/main/src/auto-reply/reply/session.ts)

长期 memory 则以 workspace Markdown（如 `MEMORY.md`、`memory/YYYY-MM-DD.md`）为基础，由 agent 文件操作及 memory 插件维护，检索接口包括 `memory_search`、`memory_get`。它不是聊天 transcript 的同义词。[Memory](https://docs.openclaw.ai/concepts/memory)

**架构推论：**如果问状态由哪个服务拥有，答案偏 Gateway；如果问完整消息在哪个生命周期边界保存，答案是 execution runtime/session 层。旧 `sessions.json` / transcript JSONL 是历史格式，不能当作当前主存储；不同页面对迁移触发方式有差异，本调查不承诺具体自动迁移行为。Compaction 的 checkpoint 也不足以证明 LangGraph 式任意执行步骤恢复。[Compaction](https://docs.openclaw.ai/concepts/compaction)

## 补查：DeepSeek Harness（2026-09-14）

官方项目：[deepseek-ai/deepseek-harness](https://github.com/deepseek-ai/deepseek-harness)。完整源码调查见 [DeepSeek Harness 专项笔记](deepseek-harness-persistence-research.md)。

执行事件与恢复由 `Session/agent-loop` 管理，`session-checkpoint-policy` 在模型请求前、顶层工具执行前和 pre-step 调用 `ctx.sessions.flush()`，物理读写由独立 JSONL provider 完成。存储契约区分 `append()` 接受写入与 `flush()` 持久化屏障。[存储契约](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/subsystems/persistence.md)、[保存时机策略](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/session/session-checkpoint-policy/src/index.ts)

Web、headless、SDK 共享 base persistence；headless 没有 HTTP server。默认 base 配置将 session root 指向 `dshHomePath('sessions')`，会话事件由 JSONL provider 保存，可使用 Zstandard 压缩。[架构](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/architecture.md)、[base 配置](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/bundle/base/cordis.patch.yml)

**架构推论：**这是三者中最清楚的“runtime 保存策略 + 可替换持久化 provider”实例。恢复会读取事件并为中断的 turn 补齐结束事件，不能理解为恢复工具调用栈或自动消除重复副作用。详见专项笔记中的恢复源码与限制。

## 三个新增样本的对照

以下是基于上文一手来源的分层归纳，不是对所有运行模式的无条件保证。

| 项目 | 谁掌握保存时机 | 谁实现存储 | Server/Gateway 的角色 |
| --- | --- | --- | --- |
| DeepSeek Harness | Session/agent-loop 与 checkpoint-policy 插件 | session-persistence-jsonl provider | 装配/暴露接口；headless 同样可持久化 |
| OpenClaw | Gateway 管理会话元数据，runtime 驱动 transcript 写入 | Gateway 主机上的 per-agent SQLite/session 存储模块 | 会话权威、生命周期与运行协调 |
| Hermes | agent 正常保存 transcript，gateway 协调异常补写 | 共享 SessionDB/SQLite | 平台路由、会话管理、交付与异常处理 |

对于 shikigen，更值得借鉴的是接口与写入归属：保留 runtime 的保存边界，由独立存储实现落盘，产品层管理自身的数据语义；避免 gateway 与 agent 同时无条件追加同一条消息。
