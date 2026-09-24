# 主会话对子会话的生命周期编排

> 调研日期：2026-08-05。仅采用官方文档或官方源码。本篇比“是否有 subagent”更严格：要求主会话能发起 child，并在 child 运行期间观察、等待、追加指令、停止，最终取回结果。

## 判定口径

- **In-band**：控制能力是主 LLM 可调用的 tool；用户无需切到 UI、CLI 或自己写 SDK。
- **External**：产品有 UI/CLI/HTTP/SDK 控制面，但这些能力不会自动成为主 LLM 的工具。
- **Steer**：向同一个 child 身份追加指令；仅结束后把摘要交给主会话不算。
- **Recover**：进程或服务重启后仍能按 ID 恢复 child 的状态/历史；仅前端离开、后端仍活着不算跨重启恢复。

## 控制矩阵

符号：✅ 原生支持；◐ 部分支持或有重要限制；❌ 没有；E 仅 external；`—` 不适用。

| 系统/模式 | LLM 发起 | LLM 状态/等待 | LLM steer | LLM cancel | 结果回主会话 | External 控制 | 跨重启 |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| OpenClaw native subagent | ✅ | ✅ | ❌ | ✅ | ✅ push | ✅ | ◐ |
| OpenAI Codex subagent thread | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ◐ 未承诺 |
| Claude Code subagent | ✅ | ✅ | ✅ | ✅ | ✅ push | ✅ | ✅ 同一 session |
| Claude Code Agent Teams | ✅ | ✅ | ✅ | ✅ shutdown | ✅ message/task | ✅ | ❌ in-process |
| Deep Agents `AsyncSubAgent` | ✅ | ✅ | ✅ | ✅ | ✅ query | ✅ | ✅ 依赖 server |
| LangGraph Agent Server（裸 API） | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ 全套 | ✅ |
| OpenCode `task` child | ✅ | ❌ | ❌ | ❌ | ✅ 同步 | ✅ 全套 | ◐ |
| Hermes `delegate_task` | ✅ | ◐ completion | ❌ | ❌ | ✅ | ✅ TUI | ❌ active run |

矩阵最关键的一点是：**LangGraph Agent Server 和 OpenCode Server 的外部 API 很完整，但不等于主 LLM 自动拥有这些控制能力**。只有把 API 包成 tools（Deep Agents Async 正是这样做）后，才算 in-band supervisor orchestration。

## 逐项核对

### OpenClaw：spawn / yield / status / cancel 完整，但 native child 不支持父 LLM 中途 steer

- 主 LLM 调 `sessions_spawn`，立即得到 `runId` 和 `childSessionKey`；这是非阻塞 child run。[Sub-agents](https://docs.openclaw.ai/tools/subagents)
- `sessions_yield` 是模型可见的等待原语；`subagents` 可列出当前 requester tree 的任务与状态，并以 `action:"cancel"` 停止指定 task。完成结果通过 announce push 回 requester。
- native child 明确禁用 `sessions_send`；`subagents` 文档只定义 list/status/debug/cancel，没有 steer action。因此不能把 ACP 的 `/acp steer` 或用户在 thread-bound 会话中的 follow-up，算成“父 LLM steer native child”。
- Gateway 重启后有有界 orphan recovery：新鲜的 aborted child 收到 synthetic resume，过旧 run 被 finalize；反复快速失败会写 recovery tombstone。completion handoff 存入 SQLite，但这不是无条件恢复承诺。

结论：OpenClaw 是很强的 **push + wait + cancel** 编排器，但 native subagent 控制面刻意不提供 parent-to-child 任意消息。

### OpenAI Codex：最接近完整的主 LLM 控制环

- Codex 的 collab tool calls 包括 `spawn_agent`、`send_input`、`resume_agent`、`wait`、`close_agent`；App Server 将 sender/receiver/new thread ID、agent status 作为一等事件暴露。[官方 App Server README](https://github.com/openai/codex/blob/main/codex-rs/app-server/README.md#items)
- 因此主 LLM 能创建 child thread、等待/读取状态、向运行中或已完成 child 追加输入、恢复 inactive child，并关闭 child；结果通过 wait/完成事件返回。
- CLI/App 的 agent 视图属于 external 可观察面；它补充人工切换与 steer，但不是 in-band 能力的来源。
- 官方文档/源码说明了 thread 与 resume tool，却没有稳定承诺“本地进程退出后，父 session 能重建仍在运行的 child execution”。保守标为：历史可持久化，active child 跨进程恢复未承诺。

### Claude Code subagent：现版本已不再只是一次性 Agent tool

- `Agent` tool 可前台或后台启动 subagent；后台任务默认并发运行，完成通知在后续 turn 返回，`/tasks` 是人工状态面。[Subagents](https://code.claude.com/docs/en/sub-agents#run-subagents-in-foreground-or-background)
- 主 Claude 可用 `SendMessage(to=<agent-id|name>)` 恢复已完成 child，也可对运行中的 child 发 mid-task course correction；可用 `TaskStop` 停止任务。由用户在 `/tasks` 中停止的 child 与由 Claude `TaskStop` 停止的 child，后续 auto-resume 规则不同。
- child 完成后主会话得到 agent ID；非 Explore/Plan child 的独立 transcript 持久化。恢复同一主 session 后，官方明确支持在重启 Claude Code 后继续该 subagent。
- 状态面是混合的：LLM 收 completion/failure notification 并可继续控制；详细列表、attach、人工 stop 则在 `/tasks`/subagent panel。

结论：按 2026-08 文档，Claude Code 普通 subagent 已具备 **spawn + notify + steer/resume + stop + restart resume**，不能再归为纯一次性 invocation。

### Claude Code Agent Teams：lead 真正监督 teammates，但恢复是明显短板

- team lead 是创建、spawn、协调 teammates 的主 session；每个 teammate 有独立 context、共享 task list 和 mailbox。[Agent Teams](https://code.claude.com/docs/en/agent-teams)
- lead/teammate 使用 `SendMessage` 定向通信；消息自动投递，idle/error 自动通知 lead，所有 agent 可读任务状态。用户也可让 lead wait、nudge、redirect。
- shutdown 通过 team protocol 请求；官方提示 shutdown 可能等待当前 request/tool call 才结束。只有 lead 能管理团队，不能嵌套 team。
- in-process teammate 不支持 `/resume`/`/rewind` 恢复；主 session 恢复后可能还记着已不存在的 teammate，只能重新 spawn。故 active team 不具备可靠跨重启恢复。

### Deep Agents AsyncSubAgent：把 Agent Server 生命周期 API正式包装成 LLM tools

- supervisor LLM 原生获得 `start_async_task`、`check_async_task`、`update_async_task`、`cancel_async_task`、`list_async_tasks`。[Async subagents](https://docs.langchain.com/oss/python/deepagents/async-subagents)
- start 创建 server thread/run 并立即返回 task/thread ID；check 读状态和最终输出；update 在同一 thread 上以 interrupt multitask strategy 创建新 run；cancel 调 server `runs.cancel()`。
- child 在自己的 thread 上保留状态。每个 run 是标准 LangGraph run，可在 LangSmith 中观察；持久性来自 Agent Protocol server/Agent Server，而非 supervisor 进程里的线程。
- 因而它是本表里最清晰的“**外部 durable runtime + 自动生成 supervisor tools**”参考实现。恢复强度取决于后端是否真正持久化 threads/runs/checkpoints。

### LangGraph Agent Server：durable orchestration substrate，不是开箱即用 supervisor

- Agent Server 把 assistants、threads、runs 与 checkpoints 持久化到数据库，用 durable queue 执行；worker 中断后可从最后 checkpoint 恢复。[Agent Server](https://docs.langchain.com/langsmith/agent-server)
- SDK/API 可 create run、get status、`/join` 等待、`/stream` 监控输出、cancel；cancel 的 `interrupt` 保留 run/checkpoints，可后续检查或从 checkpoint 恢复。[Cancel a run](https://docs.langchain.com/langsmith/cancel-run)
- 新输入遇到 active run 时可用 enqueue/reject/interrupt/rollback 等 multitask strategy；这能实现 steer，但调用者默认是应用程序。
- 所以裸 Agent Server 在 LLM 列全部为 ❌：它提供的是 control-plane primitives。只有应用把这些 endpoint 包装成模型 tools，才成为“主会话管理 child”。

### OpenCode：child session graph 是一等资源，但 `task` 对主 LLM仍是同步调用

- primary agent 通过 `task` 调 subagent，运行时建立可导航 child session；TUI 支持 parent/child navigation。[Agents](https://opencode.ai/docs/agents)
- 官方没有给 primary LLM 提供 child status/wait/send/abort tools；`task` 完成后把结果返回父调用，因此 in-band 仍是同步 agent-as-tool。
- 但 external Server 很完整：`GET /session/:id/children`、全局 status、message history、同步/异步 message、`POST /session/:id/abort`。[Server API](https://opencode.ai/docs/server)
- 这些 endpoint 足以让外部应用实现监控、追加 prompt、abort 和取结果；官方没有承诺 active child 在 server 进程重启后续跑，故只承认 session 数据可再寻址，不判 full recover。

### Hermes：delegation 有观察面，但父 LLM控制能力弱于 UI

- `delegate_task` 创建隔离 child `AIAgent`；可传单任务或 batch，只有最终 summary 进入 parent context。[Delegation](https://hermes-agent.nousresearch.com/docs/user-guide/features/delegation/)
- 当前官方源码文档同时提供 `background=true`，并在 TUI `/agents` 展示 live tree、成本/token/文件、pause/kill 和完成后逐 turn history。[官方文档源码](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/delegation.md#monitoring-running-subagents-agents)
- 但这些 pause/kill/history 是 external TUI 控制；`delegation` toolset 只有 `delegate_task`，没有 parent LLM 可调用的 check/send/cancel sibling tools。因此只算发起 + completion delivery，不算完整 supervisor loop。
- parent turn 被中断时 active children 会被取消；durable 长任务官方建议改用 cronjob。故 active delegated child 不支持跨进程/重启恢复。

## 明确降级/排除

- **Deep Agents sync subagent**：`task` 阻塞 supervisor，跨 invocation stateless，不能 update/cancel；它是 agent-as-tool，不是 child lifecycle orchestration。[Sync subagents](https://docs.langchain.com/oss/python/deepagents/subagents)
- **DeerFlow `task`**：一次隔离 invocation，返回 final output；没有稳定 child session ID、后续消息或 cancel/resume 控制面。[DeerFlow subagents](https://deerflow.tech/en/docs/harness/subagents)
- **Gemini CLI subagent**：独立 context loop 与最终 findings，不提供可寻址 child lifecycle；顶层 session resume 不能推导出 child resume。[Gemini CLI subagents](https://geminicli.com/docs/core/subagents/)

## 设计结论

真正的 supervisor-managed child session 至少需要六个原语：`spawn`、`inspect/list`、`wait/subscribe`、`send/steer`、`cancel`、`get_result`；durable 版本再加 `resume/recover`。

实现上应分成两层：底层 `Thread/Run Service` 负责 ID、状态机、event stream、checkpoint 和取消；上层 `Supervisor Tools` 把最小安全控制面暴露给主 LLM。Deep Agents Async 展示了这两层的组合，LangGraph Agent Server 展示底层，Codex/Claude 展示产品级 in-band 控制，OpenCode 则展示“底层 API 有能力，但主 LLM tool surface 尚未接通”的典型差别。
