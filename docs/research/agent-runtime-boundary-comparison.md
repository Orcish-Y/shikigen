# Run 与持久化边界：对照项目评估

调查日期：2026-09-14。本文补充 [原持久化调查](agent-persistence-ownership-research.md)，重点是执行、run 生命周期与 HTTP 的边界。外部事实来自当日官方文档；上游分支未固定 commit，未运行外部项目。设计建议与事实分开陈述。

## 结论

对于 shikigen 希望支持 CLI、服务端、多轮 Goal 和子 Agent 的目标，**核心执行和可复用 run 编排独立于 HTTP 的原设计更合适**。但“独立于 server”最好定义为不依赖网络协议、Request 和连接生命周期，而不是把全部功能搬进 Agent 类。

建议分出三层：HTTP/gateway 适配层、run 应用服务或 runtime、单次 Agent 执行。存储实现通过接口注入。独立模块可先与 HTTP 共进程部署；无需为了分层立刻增加 worker 服务。

以下样本支持这种职责分离，但并不一致采用“gateway 只做网络和鉴权”的产品架构。

## 对照事实

| 项目 | 核心执行 | Run / 会话协调 | 保存职责 | 对设计判断的启发 |
| --- | --- | --- | --- | --- |
| DeepSeek Harness | `core/agent-loop` 实现 Agent 驱动 | Session 和 Agent 服务可由不同应用组合使用 | 独立 persistence 服务与 provider | 最直接支持执行和持久化不依赖 Web server |
| OpenClaw | `agentCommand → runEmbeddedAgent` | Gateway 接受 run、处理会话，embedded runtime 管执行队列/超时 | Gateway 管会话元数据，runtime 写 transcript | Gateway 是常驻控制服务，名称不能直接理解成薄 HTTP 层 |
| Hermes | `AIAgent` / `agent/conversation_loop.py` | GatewayRunner 管平台会话、运行中消息、中断和交付 | Agent 正常写历史；共享 SessionDB 实现存储 | 独立 Agent 可以与较厚的产品协调层共存 |
| deer-flow（本地） | harness 内 graph/runtime | harness `runtime/runs/worker.py` | harness persistence；gateway lifespan 装配 | 生命周期装配在 gateway 不等于执行依赖 HTTP |

### DeepSeek Harness

官方架构列出 `web`、`headless`、`sdk` 等 profile；共享 `dsh-base` 包含模型、工具、persistence。`headless` 增加无 server 的一次性 runner。`core/agent` 定义接口，`core/agent-loop` 提供默认驱动，Session 保存执行事实；Web 接口只是组合中的一种入口。[官方架构](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/architecture.md)

存储契约为 `SessionPersistence.create/open/stat/list`，返回具有 `read/append/flush/close` 的 SessionHandle。`append` 的接受与 `flush` 的耐久保证明确区分；恢复时由 agent-loop 补齐中断 turn 的结束事实，provider 管物理日志和写入所有权。[官方 persistence 契约](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/subsystems/persistence.md)

**推论：**保存策略与恢复语义属于执行系统，数据读写可独立替换。这里的恢复不是恢复工具调用栈，也不保证工具外部副作用不重复。

### OpenClaw

官方描述的 run 流程是：RPC 校验、解析会话、保存元数据并返回 runId；`agentCommand` 准备运行；`runEmbeddedAgent` 串行化会话执行、管理超时并转发事件；`agent.wait` 等待终态。运行还以 `activeWriterRunId` 和 `expectedWriterRunId` 防止过期执行写 transcript。[Agent loop](https://docs.openclaw.ai/concepts/agent-loop)

Gateway 本身是常驻 daemon，拥有消息平台连接，暴露 WebSocket 控制 API，提供状态和事件。因此它同时是产品运行宿主与连接入口。[Gateway architecture](https://docs.openclaw.ai/concepts/architecture)

**推论：**OpenClaw 不能当作“server 越薄越好”的佐证，也不能因为 Gateway 拥有状态就推断模型/工具 loop 写在 HTTP handler 中。部署宿主、产品控制层和执行模块是不同维度。

### Hermes

官方将 AIAgent 定义为核心编排引擎，`run_agent.py` 是 facade，执行 loop 位于 `agent/conversation_loop.py`。`chat()` 和 `run_conversation()` 是入口；模型请求、工具调用、压缩与重试在 Agent 内，CLI、gateway、ACP 通过 callback 消费进度。[Agent Loop Internals](https://hermes-agent.nousresearch.com/docs/developer-guide/agent-loop)

GatewayRunner 则负责规范化消息之后的会话路由、权限、命令、Agent 创建和平台结果交付，并对运行中的会话提供排队和中断机制。因此 Gateway 的产品协调职责明显超过网络转发。[Gateway Internals](https://hermes-agent.nousresearch.com/docs/developer-guide/gateway-internals)

CLI 和 gateway 共用 SQLite SessionDB。正常 transcript 由 Agent 保存；当 Agent 声明写入归属时 gateway 跳过写入，异常路径另行核查归属后补写。数据库也保存 gateway 路由和交付义务。[Session Storage](https://hermes-agent.nousresearch.com/docs/developer-guide/session-storage)

**推论：**有价值的是共享核心和明确写入归属。Gateway 可以拥有自己的产品状态，而无需重复实现 Agent 的正常消息保存。

### deer-flow 本地补核

本次读取本地 `backend/app/gateway/deps.py` 与 harness 的 worker：`langgraph_runtime()` 初始化 persistence engine/checkpointer；worker 接收 `RunContext`，并把 checkpointer 接到执行 agent。[装配入口](/home/orcish/code/deer-flow/backend/app/gateway/deps.py:348)、[RunContext](/home/orcish/code/deer-flow/backend/packages/harness/deerflow/runtime/runs/worker.py:315)、[执行接入](/home/orcish/code/deer-flow/backend/packages/harness/deerflow/runtime/runs/worker.py:703)

**推论：**存储由启动入口打开和关闭很自然；可复用 worker 不必自己决定数据库配置或进程资源生命周期。

## 对 shikigen 的具体含义

结合本轮本地核查，目前不是整个核心都写在 server：harness 已有执行 loop、RunExecution/Registry、checkpoint 和依赖 MessageJournal 的 middleware；`server.py` 的 lifespan 装配职责也合理。主要需要继续分离的是 HTTP route 中创建 run、创建持久记录、启动后台执行和收尾等工作。[server.py](/home/orcish/code/shikigen-agent/app/server.py)、[run 路由](/home/orcish/code/shikigen-agent/app/routes/run.py:198)

独立执行编排现已迁入 `packages/harness/shikigen/runtime/run_execution.py`，并通过 `shikigen.runtime` 提供共享运行入口。此前文件留在 `app/` 也不等于与 HTTP 耦合；此次迁移进一步使完整运行能力随 harness 包分发。[run_execution.py](/home/orcish/code/shikigen-agent/packages/harness/shikigen/runtime/run_execution.py)

| 做什么（What） | 为什么（Why） | 接口方向（How，建议而非现有承诺） |
| --- | --- | --- |
| HTTP 层只做请求解析、认证入口、响应/流编码和错误映射 | 切换 CLI、cron、子 Agent 不应重写 run 流程 | 调用独立 run service；将内部事件编码为当前使用的 SSE 响应 |
| 独立 run 服务管理开始、取消、等待、收尾及持久状态 | 这些能力跨网络入口复用，又比单次模型/工具 loop 更高层 | 对外提供 start/cancel/wait/subscribe 类能力；复用 RunExecution/Registry |
| Agent execution 保留模型、工具、middleware、执行 checkpoint | 单轮执行不必知道 HTTP、用户表或后台作业资源 | 输入运行上下文和取消信号，输出执行结果/事件 |
| 存储实现保持可注入，执行 journal 与产品查询职责分开 | 保存语义、查询需求和物理后端可以独立演进 | MessageJournal、checkpointer、run repository 等窄接口 |
| Server/CLI 启动入口装配并关闭资源 | 进程级连接池/配置需有明确生命周期 | lifespan 或 async context manager |

这项拆分的验收问题是：**不启动 FastAPI，能否通过同一个 run 服务完成启动、取消、终态持久化和事件订阅？** 如果可以，核心边界基本成立；不必强求存储文件全部在 harness 目录。

还有一项比移动文件更重要的收尾语义：本轮本地核查发现 HTTP 旧路径先发布内存终态/关流，再由外层完成数据库收尾；新的 `RunSettlement` 骨架采取先提交再发布。迁移时应统一该语义，避免客户端观察到的完成状态早于持久记录。此处是静态调用链判断，未执行故障注入；真正跨 checkpoint、journal 与 run 表的一致性仍需单独定义。[旧路由收尾](/home/orcish/code/shikigen-agent/app/routes/run.py:147)、[新编排骨架](/home/orcish/code/shikigen-agent/packages/harness/shikigen/runtime/run_execution.py)

## 取舍

当前做法适合作为单一 HTTP 产品的阶段性实现：装配直接、易追踪。若长期只暴露 HTTP，也可以把 run 应用服务保留在 app 包。

原设计更符合本项目长期目标，前提是把它落实为“薄协议层 + 独立 run runtime + Agent execution”。不要把单次 Agent 工厂变成同时负责用户权限、后台任务、数据库迁移和网络交付的总管。也不需要借此次边界调整一次性引入队列系统或分布式 worker。
