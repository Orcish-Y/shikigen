# 常见 Agent 的 Multi-session 能力版图

> 调研日期：2026-08-05。仅采用官方文档或官方源码。本文中的“session”指有稳定身份、独立状态且可被再次寻址的执行上下文；不能把所有 subagent invocation 都叫作 multi-session。

## 判定口径

- **A — 用户多会话**：用户能创建、列出、切换或恢复多个独立顶层会话。
- **B — 父子会话**：主 Agent 能创建有父子关系、可单独观察或通信的 child session/thread。
- **C — 后台持久任务/会话**：调用立即返回，任务继续运行，并能稍后重连、查询、更新或恢复；仅“后台线程执行但父调用仍等待”不算。
- **D — 一次性隔离 invocation**：有干净 context，但完成后只返回结果，没有可继续对话的稳定 child session。
- **Session-native**：session/thread 是公开的一等资源，有 ID 与 lifecycle API；“内部恰好用了一个 agent loop”不够。

## 总表

| 产品/框架 | A | B | C | D | 结论 |
|---|:---:|:---:|:---:|:---:|---|
| OpenClaw | ✅ | ✅ | ✅ | ✅ | 顶层与 child 都是 session-native，能力最完整 |
| OpenAI Codex | ✅ | ✅ | 部分 | ✅ | 顶层与本地 agent thread 是 session-native；本地 child 跨进程恢复未承诺 |
| Claude Code | ✅ | ✅ | ✅ | ✅ | 顶层、subagent、Agent View 均有明确生命周期；Agent Teams 仍实验性 |
| Gemini CLI | ✅ | ⚠️ | ❌ | ✅ | 顶层 session-native；subagent 主要是一次调用型隔离 loop |
| OpenCode | ✅ | ✅ | ✅（Server/API） | ✅ | session graph 是一等资源；CLI 后台管理面不如 API 完整 |
| Hermes Agent | ✅ | ✅（运行期） | ⚠️ | ✅ | child 是独立 `AIAgent`，但运行中任务不能跨进程恢复 |
| DeerFlow 2.x | ✅ | 逻辑父子 | ❌ | ✅ | `task` 是隔离 invocation，不是真正持久 child session |
| LangGraph / Agent Server | ✅ | 可建模 | ✅ | ✅ | `thread`/`run`/checkpoint 是 session-native 基础设施 |
| Deep Agents | 继承 LangGraph | 同步为 D；异步为 B | ✅（Async） | ✅（Sync） | 必须区分同步 `task` 与 AsyncSubAgent |

## 逐项核对

### OpenClaw

- A：Gateway 按 `sessionKey` 路由并持久化会话；`openclaw sessions` / `sessions.list` 可列出，`/new`、`/reset` 创建新 session ID。[Session management](https://docs.openclaw.ai/session)
- B/D：`sessions_spawn` 默认以 `mode:"run"` 创建独立后台 child session/run，立即返回 `runId` 与 `childSessionKey`；`sessions_yield` 等待，`subagents` 查看或取消。默认 `context:"isolated"`，也可 `fork` 父 transcript。[Sub-agents](https://docs.openclaw.ai/tools/subagents)
- C：`sessions_spawn(thread:true, mode:"session")` 创建 thread-bound 持久 child；后续消息继续路由到同一 child。completion handoff 会持久化，并有有限的 restart orphan recovery。
- 并发：全局 subagent lane 默认 8；每个 session 默认最多 5 个 active child（可配 1–20），最大深度 5。child 有独立 transcript/context/token，但 OS sandbox 需另行配置。

### OpenAI Codex

- A：CLI 用 `/new`、`/resume`、`/fork`，命令行用 `codex resume` / `codex fork`；App/IDE 可在一个项目维护多个 chat。[CLI commands](https://learn.chatgpt.com/docs/developer-commands?surface=cli)
- B：主线程通过 `spawn_agent` 创建独立 agent thread，并用 `send_input`、`wait_agent`、`resume_agent`、`close_agent` 管理；CLI `/agent` 可切换查看。并发由 `agents.max_concurrent_threads_per_session` 控制，官方不承诺未配置时的固定值。[Subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents)
- 隔离：context/thread 独立，但默认继承父 turn 的 sandbox、approval 与 live overrides；文件系统默认共享，写密集并发应使用 worktree。
- C：Cloud/ChatGPT Work 提供 hosted background/offload；本地 UI 能观察和 steer 活跃 child，但官方未承诺退出进程后单独恢复 child，因此本地 C 只标“部分”。
- D：`codex exec` 可一次执行；默认 rollout 可用 `codex exec resume` 延续，只有 `--ephemeral` 明确不落盘。[Non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode)

### Claude Code

- A：`claude -c` 继续当前目录最新会话，`claude -r <id|name>` 或 `/resume` 恢复指定会话。[CLI reference](https://code.claude.com/docs/en/cli-usage)
- B：主 Agent 通过 `Agent` tool 创建 foreground/background subagent；child 有独立 context/transcript，可用 `isolation: worktree`。subagent 不能继续 spawn subagent。[Subagents](https://code.claude.com/docs/en/sub-agents)
- B（实验）：Agent Teams 由 lead session 创建独立 teammate sessions，共享 task list 与 mailbox，使用 `SendMessage` 通信；但官方明确存在 session-resumption limitations。[Agent teams](https://code.claude.com/docs/en/agent-teams)
- C：Agent View 提供 `claude --bg`、`claude agents`、`claude attach`、`claude logs`、`claude stop`；后台 session 可继续运行并重新接管。[Agent View](https://code.claude.com/docs/en/agent-view)
- 并发：`CLAUDE_CODE_MAX_TOOL_USE_CONCURRENCY` 同时控制只读 tools 与 subagents，默认 10。[Environment variables](https://code.claude.com/docs/en/env-vars)

### Gemini CLI

- A：聊天和 tool history 按项目保存在 `~/.gemini/tmp/<project_hash>/chats/`；用 `--resume/-r`、交互 `/resume`、`--list-sessions` 管理，默认 retention 为 30 天。[Session management](https://geminicli.com/docs/cli/session-management/)
- B/D：subagent 以 agent tool（policy 层统一为 `invoke_agent`）暴露，可自动 delegation 或 `@agent_name`；每次在独立 context loop 中运行，只回传 findings。[Subagents](https://geminicli.com/docs/core/subagents/)
- 官方未文档化 child ID、child transcript resume、固定并发数或 detached worker，所以它的 subagent 应归 D，而不是持久 B/C。A2A remote agent 是连接远端 agent 的能力，也不等于 CLI 自己提供持久 child session。[Remote agents](https://geminicli.com/docs/core/remote-agents/)

### OpenCode

- A：TUI `/sessions`（别名 `/resume`、`/continue`），CLI `--continue`、`--session`、`--fork` 与 `opencode session list` 管理会话。[CLI](https://opencode.ai/docs/cli/)
- B：primary 通过 `task` tool 或 `@subagent` 建立 child session；UI 有 parent/child navigation，Server 提供 `GET /session/:id/children`，因此父子 session graph 是公开资源。[Agents](https://opencode.ai/docs/agents/)
- C：Server 的 `POST /session/:id/prompt_async` 立即返回；客户端可通过 status/messages/events 再观察，TUI 还能 attach 到长期 `serve/web` backend。官方没有固定并发上限。[Server API](https://opencode.ai/docs/server/)
- child context 独立，但文档未承诺自动 worktree，默认同 workspace 的文件仍可能共享。

### Hermes Agent

- A：CLI/TUI/gateway 会话存入 SQLite `~/.hermes/state.db`；`hermes --continue`、`--resume <id|title>`，TUI `/sessions`、`/switch` 可恢复或切换。[Sessions](https://hermes-agent.nousresearch.com/docs/user-guide/sessions/)
- B/D：`delegate_task(goal, context)` 或 batch `tasks=[...]` 动态创建 child `AIAgent`；每个 child 有新 conversation 和独立 terminal session，最终只回传 summary。[Delegation](https://hermes-agent.nousresearch.com/docs/user-guide/features/delegation/)
- 顶层 delegation 默认后台并立即返回 handle；默认并发 3、深度 1。完成但未交付的 event 可在重启后重投，但运行中的 child 重启后变 `unknown`，不能恢复；所以不是 durable C。
- leaf child 默认不能 delegation；`role="orchestrator"` 加大 `max_spawn_depth` 才能嵌套。terminal session 独立不代表独立容器或文件系统。

### DeerFlow 2.x

- A：App `thread` 有唯一 ID、history、artifacts、agent ref；配置 SQLite/Postgres checkpointer 后可跨重启恢复，默认 memory checkpointer 不可。[Agents and threads](https://deerflow.tech/en/docs/application/agents-and-threads)
- D：Lead 调 `task(agent, task, context)`；runtime 查 registry 后创建一次隔离 agent invocation，完成/超时后把 final output 当 tool result 返回。[Subagents](https://deerflow.tech/en/docs/harness/subagents)
- 每 turn 默认最多并行 3 个 `task` call，默认 timeout 900 秒。child 不看父完整 conversation，但没有 child session ID、后续投递、checkpoint/resume API，所以只是逻辑父子，不是 session-native B/C。
- `invoke_acp_agent` 管理外部 ACP child process，官方同样只承诺 invocation lifecycle，不能据此推断可恢复 session。

### LangGraph / Agent Server 与 Deep Agents

- LangGraph checkpointer 把状态按 `thread_id` 保存为 checkpoints；thread 可取当前/历史状态、interrupt/resume、time travel 与 fork，因此 A 是框架的一等抽象。[Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
- Agent Server 将 assistants、threads、runs、checkpoints 和 task queue 持久化；每个 thread 同时最多执行 1 个 run，每 worker 默认并行 10 个 runs，不同 threads 可并行。[Agent Server](https://docs.langchain.com/langsmith/agent-server)
- 普通 subgraph 有三种模式：`checkpointer=None` 是 per-invocation（可在本次调用内 durable，但下次从新状态开始），`True` 是 per-thread，`False` 完全 stateless。[Subgraphs](https://docs.langchain.com/oss/python/langgraph/use-subgraphs)
- Deep Agents 同步 `task` 调用 `SubAgent`/`CompiledSubAgent`：父 Agent 阻塞，child 在干净 state 中完成后只回最终结果；官方明确称其跨 invocation **stateless**，所以是 D，不应称持久 child session。[Synchronous subagents](https://docs.langchain.com/oss/python/deepagents/subagents)
- `AsyncSubAgent` 才是 B+C：`start_async_task` 创建独立 server thread/run 并立即返回 thread ID；`check_async_task`、`update_async_task`、`cancel_async_task`、`list_async_tasks` 管理它。它在自己的 thread 上有状态，可并发且 non-blocking。[Async subagents](https://docs.langchain.com/oss/python/deepagents/async-subagents)

## 最终判断

若问题是“哪些产品真正把 session 当原生资源”，答案是：**OpenClaw、Codex、Claude Code、OpenCode、LangGraph Agent Server**；Deep Agents 的 **AsyncSubAgent** 也属于这一类。Hermes 只有运行期 child session，缺少 durable resume；Gemini CLI、DeerFlow 与 Deep Agents 同步 `task` 的 subagent 则主要是 **D：一次性隔离 invocation**。

还应区分三个经常被混淆的“持久”含义：

- **Transcript persistence**：只保证历史可读；不表示正在运行的工作能继续。
- **Run durability**：进程或 worker 中断后能从 checkpoint 继续；LangGraph Agent Server 明确提供这一层。
- **Detached reattachment**：前端离开后任务仍跑，用户稍后凭 ID 重新观察或控制；OpenClaw persistent child、Claude Agent View、OpenCode async API 和 Deep Agents AsyncSubAgent 属于这一层。

同样，context 隔离不等于执行环境隔离：Codex、OpenCode、Hermes、DeerFlow 的 child 都可能共享 workspace 或 backend。需要并行修改文件时，应另外提供 worktree、sandbox/container 或明确的文件 ownership，而不能只依赖“不同 session”。

因此，产品宣称“支持 subagent”时，应继续追问 child 是否有 ID、能否再投递、前端退出后是否继续、进程重启后是否恢复，以及文件系统是否真正隔离。

设计自己的 harness 时，建议拆成 `SessionStore`（A）、`spawn_child_session`（B）、`BackgroundRunManager`（C）和 `invoke_isolated_agent`（D），避免用一个 `task` 名称掩盖完全不同的生命周期。
