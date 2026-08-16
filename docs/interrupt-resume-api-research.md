# Agent Interrupt / Approval / Resume API 研究

> 研究日期：2026-08-16  
> 范围：Hermes、OpenClaw、Codex App Server、Claude Managed Agents / Agent SDK、DeerFlow  
> 资料原则：只使用官方文档、官方仓库及本地 DeerFlow 源码。

## 结论先行

当前项目应保留：

```http
POST /api/threads/{thread_id}/stream
```

只负责“发送一条新的用户消息，并创建一个新的 run”。对于 checkpoint interrupt 的恢复，建议增加独立接口：

```http
POST /api/threads/{thread_id}/runs/{run_id}/resume
Content-Type: application/json

{
  "interrupt_id": "...",
  "value": { "approved": true }
}
```

该请求应：

- 继续使用相同 `thread_id`，以便 LangGraph 找到原 checkpoint；
- 通过 `Command(resume={interrupt_id: value})` 恢复，不能伪装成新的 `HumanMessage`；
- 创建一个新的 `run_id`，并记录 `resumed_from_run_id` 指向被中断的 run；
- 将原 run 固定为 `interrupted` / `requires_action`，不重新打开它；
- 把授权答案作为控制事件持久化，而不是普通聊天消息。

这是基于本项目当前语义作出的选择：**一个 run 就是一次 Loop / graph invocation**。checkpoint resume 会启动一次新的 invocation，因此新建 run 最一致。市面产品若在原进程中等待批准，通常沿用同一 run/turn；这与“调用已经结束、以后从 checkpoint 重放”的实现并不相同。

## 先区分三件事

1. **新消息**：开始一个新的用户 turn，通常创建新 run/turn。
2. **批准 interrupt**：回答一个已有的、带 ID 的待决请求，不应被建模成任意聊天消息。
3. **流重连**：只是重新订阅已有执行或读取持久化历史，不应再次启动或恢复 graph。

还要区分 human approval 与用户主动 cancel：approval 是可继续的待决状态；cancel/interrupt execution 通常是终止状态。

## 横向比较

| 系统 | 新消息与批准/恢复接口 | identity | 状态与事件 | 断线后 |
|---|---|---|---|---|
| Hermes | `POST /v1/runs` 新建；`POST /v1/runs/{run_id}/approval` 单独批准 | 批准后沿用同一 `run_id` | run 保存 pending approval；批准后原 run 继续 | 可重新订阅 run events 或查询 run；短期事件缓存不是永久历史 |
| Codex App Server | `turn/start` 新 turn；批准通过服务端发出的 JSON-RPC request 的 response 返回 | 同一 `threadId`、`turnId`、`itemId` | command/file-change item 保持 pending，响应后继续同一 turn | 增量通知不是权威历史；用 thread/turn/item 读取接口对账 |
| Claude Managed Agents | `user.message` 新工作；`user.tool_confirmation` 单独确认 | 同一 session，确认通过 `tool_use_id` 精确关联；公开模型无独立 run ID | `stop_reason.requires_action`、blocking `event_ids` 和持久化事件 | 重开 event stream，并读取 event history；token deltas 不保证重放 |
| OpenClaw | `chat.send` 新 turn；`approval.get/resolve`、`exec.approval.request/resolve` 单独处理 | 精确关联 approval/session；原生 inline 流程继续原执行 | durable approval registry；requested/resolved 事件；first-answer-wins | 重新 subscribe，利用 transcript 与 approval replay 对账；普通 gateway event 不保证重放 |
| DeerFlow 通用 runs API | 同一个 `POST /threads/{id}/runs[/stream]`，body 用 `input` 或 `command.resume` 区分 | 相同 thread/checkpoint，但每次 `start_run` 创建新的 `run_id` | LangGraph interrupt 存 checkpoint；resume 是新 graph invocation | `join`/existing-run stream 用于已有 run；这与 resume graph 是两件事 |
| DeerFlow Web clarification | 前端把回答包装成隐藏 `HumanMessage`，再次 submit | 旧 run 成功结束；回答创建新 run | clarification middleware 发 artifact 后 `goto=END`，不是 LangGraph dynamic interrupt | 跟随新 run 的 stream |

## 各系统的一手证据

### Hermes

Hermes 的 API 明确分离执行创建与批准控制：`POST /v1/runs` 创建 run，`GET /v1/runs/{run_id}/events` 订阅 SSE，`POST /v1/runs/{run_id}/approval` 记录决定，文档说明决定记录后 run 会恢复。停止执行也有独立的 `POST /v1/runs/{run_id}/stop`。

因此 Hermes 的批准不是新聊天消息，也不创建新 run；它适合“原执行仍由服务器持有并等待”的模型。[Hermes API Server](https://hermes-agent.nousresearch.com/docs/user-guide/features/api-server)、[Hermes Programmatic Integration](https://github.com/nousresearch/hermes-agent/blob/main/website/docs/developer-guide/programmatic-integration.md)

### Codex App Server

Codex 的公开协议把 conversation 分成 thread、turn、item：`turn/start` 才会开始新 turn。命令执行或文件变更需要批准时，服务端向客户端发 JSON-RPC request，其中携带 `threadId`、`turnId`、`itemId`；客户端对该 request 返回 decision，原 item 和原 turn 继续完成。

`turn/interrupt` 是终止当前 turn，不是批准后的 resume；`thread/resume` 是重新打开已保存 conversation，后续用户请求仍通过 `turn/start` 创建新 turn。流式 delta 属于传输通知，断线恢复应读取持久化的 thread/turn/item 状态，而不是把 delta 当数据库事实。[Codex App Server](https://developers.openai.com/codex/app-server)

### Claude Managed Agents / Agent SDK

Claude Managed Agents 使用事件模型。普通输入是 `user.message`；工具要求人工确认时，session 进入 idle，`stop_reason` 为 `requires_action`，并给出 blocking event IDs。客户端发送 `user.tool_confirmation`，使用 `tool_use_id` 精确对应原工具调用；所有阻塞项处理后，同一 session 回到 running。

事件历史是权威记录，但 token delta preview 是 best-effort，不持久化且不能补发。断线后应重新建立 stream，并读取 event history 补齐权威事件。[Events and streaming](https://platform.claude.com/docs/en/managed-agents/events-and-streaming)、[Permission policies](https://platform.claude.com/docs/en/managed-agents/permission-policies)

Claude Agent SDK 的 `resume=session_id` 用于之后恢复同一会话上下文；它更接近普通多轮 session resume，不应与一次运行中的 tool approval 混为一谈。[Agent SDK migration cookbook](https://platform.claude.com/cookbook/claude-agent-sdk-04-migrating-from-openai-agents-sdk)

### OpenClaw

OpenClaw Gateway 通过 WebSocket 暴露控制面。`chat.send` 用于正常用户 turn；批准使用独立的 `approval.get/resolve` 或 `exec.approval.request/resolve`，并产生 `exec.approval.requested/resolved` 事件。批准记录由 durable registry 管理，解决冲突采用 first-answer-wins。

Gateway event 本身不承诺完整重放；重连后需要重新订阅，通过 session transcript、pending approval replay 和状态读取对账。原生 chat/Web UI 可以在原执行内等待批准，非原生适配器也可能先返回 approval-pending ID，但两者都没有把批准伪装成新的 `chat.send`。[Gateway Protocol](https://docs.openclaw.ai/gateway/protocol)、[Exec](https://docs.openclaw.ai/tools/exec)、[Exec approvals](https://docs.openclaw.ai/tools/exec-approvals)

### DeerFlow：必须拆开的两条路径

以下结论来自本地 `/home/orcish/code/deer-flow` 源码，检查版本为 commit `244ce7739f13d44ce7ee5679eab114eb178f89f1`。

#### A. 通用 LangGraph `Command.resume`

`backend/app/gateway/routers/thread_runs.py` 的 `POST /{thread_id}/runs` 与 `POST /{thread_id}/runs/stream` 都调用 `start_run()`。`backend/app/gateway/services.py` 中 `start_run()` 每次先创建新的 `RunRecord`；若请求包含 `command.resume`，才把 graph input 构造成 `Command(resume=...)`。

所以 DeerFlow 通用 runs API 的含义是：

- 可以复用同一个“创建 run”路由；
- request body 用 `input` 与 `command.resume` 区分；
- resume 仍然创建新的 `run_id`；
- 使用相同 `thread_id` 找 checkpoint；
- `join` 或 existing-run stream 是订阅已有 run，不是恢复 graph。

对应官方仓库：[bytedance/deer-flow](https://github.com/bytedance/deer-flow)

#### B. DeerFlow 当前 Web clarification

`backend/packages/harness/deerflow/agents/middlewares/clarification_middleware.py` 发出带 artifact 的 `ToolMessage` 后返回 `Command(goto=END)`；旧 run 正常结束。`frontend/src/core/api/api-client.ts` 的注释也明确：clarification HITL 让旧 run 成功结束，恢复通过 fresh submit；`frontend/src/app/workspace/chats/[thread_id]/page.tsx` 调用普通 `sendMessage`，并通过 `hide_from_ui` 与 `human_input_response` 携带回答，因此它在 graph 一侧仍是隐藏的用户消息。

这不是 LangGraph dynamic interrupt，也不是 `Command.resume`。它是产品层的“两次独立 run + 特殊隐藏消息”协议。用户主动取消使用的 `interrupted` 状态又是第三件事。设计本项目时不能只说“DeerFlow 用 resume”，必须先说明采用的是哪一条路径。

### LangGraph 本身

LangGraph dynamic interrupt 会把状态写入 checkpointer；恢复时需要用相同 `thread_id` 再次调用 graph，并传入 `Command(resume=...)`。节点从头重新执行，interrupt 之前的代码可能再次运行，因此副作用必须幂等。多个 interrupt 可以使用 interrupt ID 到 value 的映射精确恢复。[LangGraph Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)

LangGraph 只规定 checkpoint/thread 的恢复标识，没有规定你的 HTTP `run_id` 必须沿用还是新建；这是应用层的领域语义。

## 对当前项目的具体 API 建议

### 1. 保留新消息接口的单一语义

```http
POST /api/threads/{thread_id}/stream
```

What：接受 `message`，创建新 run、新 Loop，并返回 SSE。  
Why：调用者可以确定“发消息一定开始新 run”，重试和审计语义清晰。  
How：仍传 `HumanMessage` 给 graph。

### 2. 新增 checkpoint resume 接口

```http
POST /api/threads/{thread_id}/runs/{interrupted_run_id}/resume

{
  "interrupt_id": "approval_123",
  "value": {
    "decision": "approve"
  }
}
```

What：解析并消费指定 interrupt，创建一个 child run，返回 child run 的 SSE；响应头或第一个事件必须给出新的 `run_id`。  
Why：approval 不是自然语言聊天输入；路径中的旧 run ID 能提供精确校验、审计和幂等边界。  
How：使用旧 run 的 `thread_id` 与 `Command(resume={interrupt_id: value})` 调用 graph；新 run 写入 `resumed_from_run_id=interrupted_run_id`。

建议校验：

- thread 与旧 run 匹配；
- 旧 run 状态是 `interrupted` / `requires_action`；
- `interrupt_id` 确实仍 pending；
- 同一个 interrupt 只能成功 resolve 一次；
- 并发 resume 采用事务或唯一约束，后到请求返回 `409 Conflict`；
- request 支持 idempotency key，避免网络重试生成两个 child runs。

### 3. 将 stream 重连与执行创建分离

建议补充只读订阅接口：

```http
GET /api/threads/{thread_id}/runs/{run_id}/stream
```

它只能读取/跟随已有 run，不能创建新 run，也不能 resume graph。客户端在 `POST` 响应断线后，应使用返回的 run ID 连接这个接口；不要重试创建型 `POST` 来“续流”。

若支持 `Last-Event-ID`，持久化事件可以从该位置补发；token chunk 可继续保持易失，但必须有最终完整 message/event 作为权威事实。若暂时不能补发，则先返回 DB 中已持久化事件，再 join 当前内存流，并用 event ID 去重。

## run 与事件存储建议

`runs` 至少增加/明确：

- 状态：`pending | running | interrupted | completed | error | cancelled`；
- `resumed_from_run_id`：可空，自关联；
- 可选 `root_run_id` 或 `turn_id`：只有产品以后确实需要把多次 invocation 展示成一个逻辑任务时再加。

`run_events` 建议保存：

- `interrupt_requested`：包含 `interrupt_id`、请求类型、展示内容、checkpoint metadata；
- `interrupt_resolved`：包含 decision/value、操作者、幂等键；
- `run_resumed`：包含 source run 与 child run；
- 最终完整 assistant/tool message；
- chunk/delta 是否持久化可自行权衡，但不能成为唯一事实来源。

中间件可以观察并写入 graph 产生的 interrupt，但授权请求进入 HTTP API 后，答案应由应用服务先验证和持久化，再构造 `Command.resume`。不要期待 `abefore_agent` 把授权答案识别为 `HumanMessage`：它本来就不是用户聊天消息。

## 为什么不直接沿用原 run_id

沿用原 run ID 也可以成立，但前提是你的领域定义改成“run 是跨越多次 graph invocation 的逻辑任务”，并且要给每次 invocation 再增加 attempt/execution identity。否则会出现：

- 一个 run 有多个 started/finished 生命周期；
- 旧 SSE 与新 SSE 的事件边界模糊；
- retry、计费、耗时、错误归属难以解释；
- 原 run 已经落为 interrupted 后又被改回 running，审计历史不直观。

当前代码已经把每次 Loop 调用当作 run，因此“新 child run + lineage”改动更小、含义也更稳定。它与 DeerFlow 通用 `Command.resume` 的行为一致；而 Hermes/Codex 的同 run/turn 恢复，依赖的是原执行仍在等待的另一种生命周期模型。

## 可选的统一路由方案

如果未来希望完全采用 DeerFlow 风格，也可以把接口改成：

```http
POST /api/threads/{thread_id}/runs/stream

{ "input": { ... } }
```

或：

```http
POST /api/threads/{thread_id}/runs/stream

{ "command": { "resume": { "interrupt_id": "...", "value": ... } } }
```

两种 body 都创建新 run。这个方案通用，但调用者更容易误传同时存在的 input/command，权限和幂等逻辑也需要分支。对当前学习项目，独立 `/resume` 路由更能表达意图；内部仍可复用同一个 `start_run` application service。

## 最终决策建议

选择“外部分开、内部复用”：

- 外部 API：新消息与 resume 分开；
- 内部应用服务：共享创建 run、注册 StreamManager、状态更新和清理逻辑；
- checkpoint identity：同一 `thread_id`；
- execution identity：resume 创建新 `run_id`；
- lineage：`resumed_from_run_id`；
- approval identity：必须携带 `interrupt_id`；
- SSE identity：每个 run 独立，重连只 join 该 run。

这样既保留了当前“一次 Loop 一个 run”的模型，也避免把授权信息污染成用户聊天内容。
