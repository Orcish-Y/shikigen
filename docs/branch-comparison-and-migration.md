# 两个工作目录的差异与设计迁移建议

记录日期：2026-09-11。本文只记录分析和迁移建议，不代表已经迁移，也不新增工作区协作约定。

## 1. 比较范围与结论

| 简称 | 工作目录 | 当前分支 | HEAD |
| --- | --- | --- | --- |
| 当前项目 | `/home/orcish/code/shikigen-agent` | `master` | `2644b37f2951fa87dfe46b9e93cac184b21aab8d` |
| copy 项目 | `/home/orcish/code/shikigen-agent-copy` | `260904` | `edbc56fa522f3b61a17a8eda04dd50e2dca27527` |

比较对象是读取时的实际文件，包括 copy 中大量 staged 和未暂存修改，不能只用上述 HEAD 的 diff 代表本次结论。当前项目在分析开始时工作树干净。

**建议保留当前项目已经完成的包拆分，逐步吸收 copy 的产品 Run、事务化事件写入、重建与恢复设计。** copy 的改动包含值得学习的架构，也包含尚未收尾的实现，不能当作可以直接合并的完成版本。

证据分为三类：

- **源码事实**：从当前文件能直接确认的控制流、接口和约束。
- **本次验证**：实际运行的测试或局部复现，详见第 7 节。
- **推断／待验证**：由源码推导出的场景风险，没有完整端到端复现时明确标出。

来源链接指向本地源码，适用于当前两个目录布局。行号是本次读取时的定位参考；后续编辑可能使其偏移。本文不评价上游最新 API，也没有访问线上模型、MCP 或搜索服务。

## 2. 做得好的地方：两边分别积累了什么

### 2.1 当前项目已经具备的基础

- **可安装的 harness 包。** 根项目通过 uv workspace 引用 `shikigen-harness`，实际代码在 `packages/harness/shikigen/`；HTTP 应用和 SQLite provider 位于 `app/`。本次“在项目目录之外导入已安装 harness”的测试通过。
- **存储接口已解耦。** `ChatPersistenceMiddleware` 依赖 `MessageJournal` Protocol，没有直接导入应用层 `ChatStore`。不必为了迁移 copy 而否定这一步设计。
- **运行清理已有明确职责。** Loop 使用 TaskGroup、取消信号竞争和 finally 收尾；`RunManager.detach()` 允许消费者断连后继续执行，待任务和持久化完成再回收。
- **已存在产品消息记录、幂等键和 Thread 内序号。** copy 的优势是进一步完善规则，不是首次引入这些能力。

来源：[workspace 配置](../pyproject.toml)、[包配置](../packages/harness/pyproject.toml)、[持久化接口与中间件](../packages/harness/shikigen/middleware/chat_persistence_middleware.py)、[RunManager](../packages/harness/shikigen/run_manager.py)、[ChatStore](../app/persistence/chat_store.py)。

### 2.2 总体差异表

| 维度 | 当前项目 | copy 项目 | 判断 |
| --- | --- | --- | --- |
| 包组织 | 已完成 uv workspace 和真实包目录 | 实现主要留在根目录，新包配置未对齐 | 保留当前结构 |
| 产品 Run 与本地执行 | `RunRecord` 同时保存状态、Task、Stream | 持久 Run 保存状态，`ActiveRunHandle` 保存本地资源 | 值得迁移 |
| 状态权威 | 内存状态与数据库状态分别更新 | 产品数据库负责生命周期转换 | 值得迁移 |
| 创建 Run | 创建、开始、入口消息分别提交 | Run、running 事件、入口消息同一事务 | 值得迁移 |
| 完整消息来源 | Middleware 的模型／工具钩子 | `LangGraphV3EventAdapter` 转换 root values | 思路可取，先解决跨 Run 归属 |
| 终态发布顺序 | Loop 推送终态后，外层保存状态 | 完整事实落库后发布 | 优先迁移 |
| 消息去重 | 相同 key 忽略后续写入 | 相同 key、相同内容幂等；不同内容报错 | 可独立迁移 |
| 顺序分配 | 数据库 `MAX(seq) + 1` | `thread_sequences` 分配，支持先预留再落完整消息 | 有稳定增量关联需求时迁移 |
| Thread 排他 | 内存检查 pending/running | Thread 锁 + 数据库非终态唯一索引 | 数据库规则值得迁移 |
| 实时输出 | text、done 和完整 tool_call，响应内 output_index | 稳定消息身份、seq、文本／reasoning 增量、完整事件 | 可分阶段迁移 |
| 重连 | 断连继续执行，能查询已保存消息 | GET 既有 Run，完整历史重建并跟随 live | 值得迁移 |
| 审批恢复 | 无完整 HTTP 产品流程 | required/resolved/invalidated、准确 checkpoint、同 Run resume | 依赖状态和事务基础 |
| HTTP 取消 | RunManager 有取消能力，未暴露对应路由 | 持久化取消后停止本地任务 | 设计可取，注意订阅者收敛 |
| 重启 | 无产品 Run 启动协调器 | 校验暂停状态，丢失执行转 error | 是状态恢复，不是自动续跑 |
| 协议 | JSONL，自定义 encoder | SSE + Pydantic 契约 + JSON Schema | 优先借鉴契约，不必更换传输 |
| 使用量 | 单次 tracker，正常完成时发布 usage | invocation 结束后累加到持久 Run | 值得迁移，通知时机需补齐 |
| 子 Agent 能力 | 默认使用主 Agent 工具集合 | 可注入独立集合，server 排除两个内置工具 | 可小步迁移 |
| 故障测试 | 模块、Loop、HTTP 等测试 | 增加审批竞争、重连、真实进程崩溃场景 | 学习其验收场景 |

### 2.3 实际相同的能力，不应重复列为 copy 新增功能

逐文件排除 import 路径、类型注解和等价写法后，以下模块没有实质能力升级：

| 模块 | 实际差异 | 迁移判断 |
| --- | --- | --- |
| model | 主要是 import 路径 | 模型创建能力当前已有 |
| MCP loader | 主要是 import 路径 | HTTP/stdio MCP 加载当前已有 |
| web search/fetch/readability/text safety | 相同实现或仅 import 变化 | 真实 web 工具不是 copy 新能力 |
| task tool | 主要是 import 路径 | 两边均有 general/bash 子 Agent，等待 ainvoke 完成后返回文本 |
| GoalMiddleware | 类型注解和等价检查；执行行为相同 | 两边均识别 `/goal `、调用 evaluator、追加提醒继续模型调用 |
| TokenTracker | import 与等价字典复制写法 | 新增的是 Run 持久用量累计，不是 tracker 算法 |
| JSON Checkpointer | 局部类型注解 | 没有恢复算法升级 |
| SQLite provider | 实现相同 | 两边均使用 AsyncSqliteSaver 并 setup |
| Logging／工具错误 middleware | 类型和等价检查 | 当前项目类型更准确，建议保留 |

当前 GoalMiddleware 默认最多 5 次续跑，这仍是一次 Graph 执行内的续跑策略，不是跨进程的长时 Goal 调度器。两边 task 工具也都没有独立、可查询和恢复的后台子 Run。

当前 `GoalEvaluation` Protocol 和 `ToolCallRequest`／`ToolMessage | Command` 注解比 copy 的部分旧注解更清楚。两边工具错误中间件都重抛 `GraphBubbleUp`，不能把 copy 接入审批误说成“首次避免吞掉 interrupt”。

两边 NOTES 的阶段 4 勾选状态都落后于这些实现，判断进度应以源码和测试为准。

来源：[当前 GoalMiddleware](../packages/harness/shikigen/middleware/goal_middleware.py)、[copy GoalMiddleware](../../shikigen-agent-copy/middleware/goal_middleware.py)、[当前 task 工具](../packages/harness/shikigen/tools/task_tool.py)、[copy task 工具](../../shikigen-agent-copy/tools/task_tool.py)、[当前工具错误中间件](../packages/harness/shikigen/middleware/tool_error_handling_middleware.py)、[当前 SQLite provider](../app/persistence/sqlite_provider.py)、[copy SQLite provider](../../shikigen-agent-copy/server/persistence/sqlite_checkpointer.py)。

## 3. 值得迁移的设计：做什么、为什么、用什么接口

### 3.1 产品 Run 与本地执行资源分离

**做什么：**把用户可感知任务的生命周期，与某一次 Graph 调用及其 asyncio 资源分开。

**为什么：**一次任务可以经历多次暂停和恢复。暂停时协程可以结束，Run 仍然是 interrupted；连接断开时 Stream 消费者可以离开，Run 仍有继续执行的责任。

**接口：**copy 的 `ActiveRunHandle`、`ActiveRunRegistry`、`start_product_run()`、`resume_product_run()`，以及持久化的 `RunPersistence`。Invocation 是调用动作，不需要再生成一个公开领域 ID。

建议落点：产品生命周期和编排放在当前 `app/`，通用执行和事件广播仍放在 `shikigen`。不要把 FastAPI、产品数据库对象或 HTTP 状态码放进通用 Loop。

**验收：**暂停后仍可查询同一个 Run；resume 沿用 run_id；断开观察连接不会改变 Run 状态；本地任务回收后，已结束 Run 仍可读取。

来源：[copy 产品概念](../../shikigen-agent-copy/CONTEXT.md)、[本地 handle 与编排](../../shikigen-agent-copy/server/product_run.py:44)、[当前 RunRecord](../packages/harness/shikigen/run_manager.py:19)。

### 3.2 用业务操作封装事务，完整事实先提交再发布

**做什么：**把“创建任务”“结束任务”“接受审批”变成各自原子的存储操作，由操作返回已提交事件。

**为什么：**当前创建流程分为 `create_run()`、`start_run()`、Middleware 记录入口消息；结束流程则先在 Loop 推送终态，再由 `run_and_persist_status()` 更新数据库。中间失败会留下部分事实。

**接口：**copy 的 `create_run(entry_message=...)` 在一次事务中保存 Run、running 事件和用户消息；`complete_run()` 等同时更新状态并写 lifecycle 事件；`RunEventIngestor` 等待提交完成后再 publish。

这类模块的价值是让调用方不必掌握多次写入的顺序和回滚规则。不要仅把原来的三次调用包进一个函数，却仍分别 commit。

**验收：**事务失败不留下半个 Run 或半组审批；落库失败时，观察者不会先收到成功终态。允许 token delta 先展示，但不能把它声明为已经保存的完整历史。

来源：[当前 HTTP 编排](../app/routes/run.py:147)、[copy 创建事务](../../shikigen-agent-copy/server/persistence/run_persistence.py:287)、[终态事务](../../shikigen-agent-copy/server/persistence/run_persistence.py:980)、[事件写入与发布](../../shikigen-agent-copy/server/product_run.py:121)。

### 3.3 把数据不变量放进数据库和语义明确的接口

**做什么：**增加非终态排他、状态转换前置条件，以及“同身份必须同内容”的消息幂等规则。

**为什么：**当前 `RunManager` 的排他只存在于内存；`ChatStore._set_run_status()` 校验归属，但没有在 UPDATE 中限定允许的旧状态；重复 event_key 会直接返回原 seq，不比较内容。

**接口与机制：**copy 使用部分唯一索引 `uq_runs_one_nonterminal_per_thread`、状态相关 CHECK、`WHERE status = ...` 的条件更新，以及 `append_message()` 中的 payload 比较。相同 ID 对应不同内容时抛出 `DurableEventConflictError`。

**验收：**同一个 Thread 的 interrupted Run 也阻止新 Run；重复完整消息不增加事件；同 ID 不同内容显式失败；终态不能被另一条正常完成路径覆盖。

限制：数据库可以保证排他，不等于执行资源已跨进程协调。HTTP 层还必须把数据库冲突转换成明确响应，copy 在新建 Run 路径上尚有缺口，见第 4 节。

来源：[当前写入和状态更新](../app/persistence/chat_store.py:180)、[copy schema](../../shikigen-agent-copy/server/persistence/run_persistence.py:109)、[copy 幂等写入](../../shikigen-agent-copy/server/persistence/run_persistence.py:713)。

### 3.4 统一框架事件转换与产品消息身份

**做什么：**集中把 LangGraph 数据转换成自己的消息模型，避免持久化与 HTTP 分别理解框架字段。

**为什么：**当前中间件保存完整消息，Loop 单独读取消息／工具流，JSONL encoder 又给输出分配索引；三条路径缺少共同的完整消息身份。

**接口：**copy 的 `adapt_message_event()`、`adapt_root_values()` 和 `adapt_root_checkpoint()`，输出自己的消息、增量和暂停状态。它不负责数据库写入或 SSE 编码。

值得单独借鉴的规则：

- AI／Human 消息要求稳定 ID；工具结果由 `tool_call_id` 推导 `tool-result:{id}`，不依赖重放时可能变化的框架消息 ID。
- 工具结果可使用显式 artifact，并区分“没有 artifact”和“artifact 明确为 null”。
- 完整消息发生身份冲突要报错；畸形的展示增量可以丢弃，并最终依赖完整消息校正。
- 明确产品支持哪些 content block；copy 目前主要提取 text 和 reasoning，不是通用多模态适配器。

**验收：**实时消息与持久历史能按身份对应；重复快照不重复写；工具结果稳定关联到工具调用；跨轮历史不归入新 Run。

**迁移前置条件：先解决 copy 的跨 Run 历史识别问题。**也不应同时开启旧持久化 Middleware 和新 Ingestor，让同一消息有两条写入路径。

来源：[当前持久化中间件](../packages/harness/shikigen/middleware/chat_persistence_middleware.py)、[copy Adapter](../../shikigen-agent-copy/server/langgraph_event_adapter.py:72)、[工具结果转换](../../shikigen-agent-copy/server/langgraph_event_adapter.py:470)。

### 3.5 稳定 seq、完整事件与临时增量分工

**做什么：**让同一消息的实时预览和完整历史共用一个 seq，完整历史覆盖对应的预览。

**为什么：**当前 `output_index` 是单次响应内的展示顺序；`StreamEvent.id` 是内存事件序号。两者都不能直接作为持久历史的消息身份。

**接口：**`reserve_message_sequence()`、`ingest_delta()`、`ingest_message()`；内部事件区分 `MessageDelta` 和 `HistoryAppended`。

copy 首次遇到消息增量时预留 Thread seq，完整消息到达后复用它；不用为半成品插入一条假完整消息。预留后没有完整消息时，序号可以有空洞，因此消费者不能假设 seq 连续。

**验收：**重复收到完整消息不重复展示；完整消息与预览不同，以完整消息为准；不能把临时 seq 当作“此前全部事件已持久化”的游标。

来源：[copy Ingestor](../../shikigen-agent-copy/server/product_run.py:140)、[seq 分配](../../shikigen-agent-copy/server/persistence/run_persistence.py:1153)、[协议无关事件](../../shikigen-agent-copy/server/run_events.py)。

### 3.6 重连读取与启动执行分开

**做什么：**提供读取既有 Run 内容的入口，并在同进程运行尚未结束时接上实时事件。

**为什么：**刷新页面或连接中断属于观察行为，不应重新创建任务、重新发送用户消息或重复调用工具。

**接口：**copy 的 `GET /api/threads/{thread_id}/runs/{run_id}/stream`，以及 `_active_product_run_response()`。

copy 的具体拼接方式是：同步注册订阅，读取持久历史中不超过本次 invocation 起点的前缀，然后消费该 invocation 的缓存与后续事件。这样读取数据库时产生的 live 事件仍在订阅队列里。

**验收：**重连不调用 Graph；数据库读取期间产生的事件不遗漏；终态 Run 不依赖内存也能重建；重复重建结果相同。

这是**全量重建协议**。copy 明确拒绝 `cursor` 和 `Last-Event-ID`，不能描述为已经实现断点增量续传。当前 JSONL 可以承载同样语义，没有必要先换成 SSE。

来源：[copy 历史与 live 拼接](../../shikigen-agent-copy/server/routes/runs.py:327)、[既有 Run 流](../../shikigen-agent-copy/server/routes/runs.py:373)、[当前 JSONL encoder](../app/routes/run.py:65)。

### 3.7 审批作为持久产品事实，同一个 Run 可以多次恢复

**做什么：**把 pending Interrupt、已接受的 decisions、取消后失效的审批记录在产品历史里。

**为什么：**HTTP 成功提交审批与 Graph 已执行恢复是两件事。进程可能在它们之间退出；审批也可能与另一份响应或取消请求竞争。

**接口：**`HumanInTheLoopMiddleware`、`accept_approval_decisions()`、`Command(resume=...)`、`cancel_run()`，以及按准确 checkpoint 坐标执行的 `aget_state(..., subgraphs=True)`。

copy 在事务中验证当前所有 Interrupt ID、每项允许的 decision，保存 resolved 事件并切回 running；之后才启动 resume。它要求一次响应当前全部 Interrupt。取消等待审批的 Run 时，保存 invalidated 和 cancelled。

**验收：**重复提交只接受一次；旧审批不能用于新一轮暂停；取消与审批竞争有确定结果；一个 Run 两次暂停后仍沿用同一个 run_id。

限制：模型允许 approve/edit/reject/respond，不等于默认服务器四种都开放；默认策略只给 `write_file` 和 `bash` 配置 approve/reject。持久化审批也不自动保证所有外部工具副作用 exactly-once。

来源：[copy 审批策略](../../shikigen-agent-copy/server/config.py)、[接受审批](../../shikigen-agent-copy/server/persistence/run_persistence.py:525)、[HTTP 恢复流程](../../shikigen-agent-copy/server/routes/runs.py:156)、[取消事务](../../shikigen-agent-copy/server/persistence/run_persistence.py:865)。

### 3.8 明确重启后如何处理每种状态

**做什么：**在服务开始接收请求前，检查未终态 Run，并区分执行丢失、持久状态损坏和依赖暂时不可用。

**为什么：**数据库里的 running 不证明进程里还有协程。反过来，checkpoint 临时不可读也不证明审批已经损坏。

**接口：**`RunRecoveryCoordinator.reconcile_all()`、`reconcile_run()`、启动前 `_recover_before_startup()`。

| 状态／条件 | copy 的处理 |
| --- | --- |
| pending/running 且本地 handle 存在 | 保持状态 |
| pending/running 且本地 handle 缺失 | 转 error，错误码 invocation_lost |
| interrupted 且准确 checkpoint 与审批记录匹配 | 保持 interrupted |
| interrupted 的审批事实不一致 | 转 error，错误码 approval_state_corrupt |
| 存储暂时不可用 | 保留状态，启动阶段重试 |

**验收：**已有终态不被重写；一个损坏 Run 不妨碍其他可处理 Run；暂时故障不被误记成永久损坏。

限制：copy 没有自动重启丢失的 invocation；其恢复策略假设进程能判断执行归属。多 worker 需要 owner/lease 等额外设计。启动扫描会重试到成功，`/ready` 是启动完成后的静态成功响应，不是持续依赖健康检查。

来源：[恢复协调器](../../shikigen-agent-copy/server/recovery.py)、[启动编排](../../shikigen-agent-copy/server/composition.py:51)、[ready 路由](../../shikigen-agent-copy/server/app.py:35)。

### 3.9 协议契约与状态错误分层

**做什么：**使用严格的产品／传输模型，并由单一来源生成跨语言契约。

**为什么：**仅靠 TypedDict 不能在运行时验证内容；各端手写同一份字段定义，容易在 null、可选字段和事件类型上漂移。

**接口：**copy 的 Pydantic `WireModel`、判别联合、`generate_wire_schema()`、`parse_sse_frame()` 和契约生成脚本。Python 生成 JSON Schema，客户端再生成类型与 Ajv 校验器；共享 fixture 验证解析和投影行为。

copy 还区分持久的 Run lifecycle error 与连接／协议 error，并把稳定错误码与内部日志详情分开。客户端连接失败不会因此把 Run 状态改成 error。

**验收：**schema 生成结果无漂移；未知字段按契约拒绝；必需 JSON 字段的显式 null 不被序列化丢失；协议错误不污染持久状态。

迁移时先定义当前 JSONL 的严格事件模型即可。copy 的通用 delta path 包含字符串、数组下标和 selector，如果当前只更新消息文本，可以保留更窄的事件接口。客户端只记录状态模型启发，不把 React UI 列为本项目迁移任务。

来源：[产品模型](../../shikigen-agent-copy/server/models.py)、[传输契约](../../shikigen-agent-copy/server/protocol/contract.py)、[schema 生成](../../shikigen-agent-copy/scripts/generate_sse_contract.py)、[客户端状态分离](../../shikigen-agent-copy/packages/react-client/src/state/run.ts:31)。

### 3.10 订阅拥有独立且可靠的释放接口

**做什么：**让同步注册的订阅即使尚未开始迭代，也能被 `aclose()` 正确移除。

**为什么：**当前 `Stream.subscribe()` 同步把队列加入集合，但清理代码位于异步生成器 finally。关闭尚未启动的生成器不会执行它的函数体，导致订阅残留。

**接口：**copy 的 `_Subscription.aclose()` 在关闭生成器前显式解绑；`EventStream[EventT]` 隐藏缓存、广播和队列细节。

**验收：**未迭代就关闭，订阅数回到零；关闭某个订阅不影响其他观察者；同步订阅后、开始迭代前发布的事件不丢失。本次已局部复现当前缺口，copy 的相关测试通过。

来源：[当前 subscribe](../packages/harness/shikigen/stream.py:136)、[copy 订阅对象](../../shikigen-agent-copy/harness/stream.py:55)、[copy Stream 测试](../../shikigen-agent-copy/tests/test_stream.py)。

### 3.11 子 Agent 独立接收工具集合

**做什么：**允许主 Agent 和子 Agent 使用不同 ToolRegistry，复制注册表容器时不修改父集合。

**为什么：**两边 task 工具都直接构建子 Agent，不自动继承主 Agent 的 middleware。copy 服务器给主 Agent 加入审批后，通过去掉子 Agent 的 `write_file`、`bash`，避免这两个内置工具绕开主 Agent 审批执行。

**接口：**`create_lead_agent(task_tool_registry=...)`、`ToolRegistry.excluding(names)`，由应用入口决定子 Agent 能力。

**验收：**父 registry 保留原能力；子 Agent 编译时只接收到显式集合；默认行为与旧调用方兼容。

限制：先注册的 MCP 工具仍在子集合中，排除两个名称不是完整权限系统；工具实例仍共享，不是资源隔离。copy 的 bash 类型子 Agent 在服务器过滤后实际上失去 bash 执行工具，但其类型名／提示词未同步改变，迁移时应核对。

来源：[copy 工厂](../../shikigen-agent-copy/harness/agent.py:18)、[registry.excluding](../../shikigen-agent-copy/tools/tool_registry.py:39)、[服务器能力组合](../../shikigen-agent-copy/server/composition.py:66)、[task 工具](../../shikigen-agent-copy/tools/task_tool.py)。

### 3.12 工厂不隐式决定 Checkpointer

**做什么：**让 `checkpointer=None` 明确表示不启用持久化，而不是偷偷实例化 JSON saver。

**为什么：**存储策略属于应用入口选择。可复用 harness 在测试、CLI 和服务器中的调用者需求不同。

**接口：**copy 直接把参数传给 `create_agent(checkpointer=checkpointer)`；当前工厂是 `checkpointer or JsonCheckpointer()`。

**验收：**传 None 不创建存储；传自定义 saver 原样使用；服务器仍显式注入 SQLite。

当前 HTTP 服务已经使用 SQLite，因此这个迁移改善的是工厂默认语义，不是给服务器首次添加持久化。copy 另加 `CheckpointsTransformer` 以观察 checkpoint 事件，这应与审批／准确恢复坐标一起评估，不能当作 saver 算法升级。

来源：[当前 agent 工厂](../packages/harness/shikigen/agent.py)、[copy agent 工厂](../../shikigen-agent-copy/harness/agent.py)、[当前服务器注入](../app/server.py)。

### 3.13 同一个 Run 累积多次 invocation 的用量

**做什么：**每次 invocation 使用独立 TokenTracker，结束后累加到同一个持久 Run。

**为什么：**审批前后是多次执行，但用户仍在完成同一个任务，用量不应在恢复时归零。

**接口：**`accumulate_run_usage(thread_id, run_id, invocation_usage)`。copy 在事务内合并总量和 by_model，执行 finally 调用它；当前只在正常完成时发送 usage，没有对应持久化字段。

**验收：**初次执行和 resume 的统计相加；错误／取消仍保存已经收到的供应商用量；读取既有 Run 可以得到累计值。

限制：copy 在 complete/interrupt 之后才累加 usage，因此收到终态后立即查询可能读到旧值；SSE 模型也没有单独 usage 帧。累加接口没有 invocation 幂等键，重复调用会重复加，finally 前崩溃会丢统计，不能直接当作严格计费账本。两边 tracker 都依赖供应商完成回调，不能保证覆盖被中断且未报告用量的调用。

来源：[当前 TokenTracker](../packages/harness/shikigen/callback_handler/token_tracker.py)、[copy 执行收尾](../../shikigen-agent-copy/server/product_run.py)、[copy 累计事务](../../shikigen-agent-copy/server/persistence/run_persistence.py:1063)。

### 3.14 配置与文件工作区应该由调用方决定

**源码差异：**当前默认配置是 `Path("config.json")`，文件工具根为导入时的 cwd；copy 两者都按源码文件位置定位到其仓库根。

copy 的默认值不随启动目录变化，但安装成包后会指向源码安装位置；当前更适合从调用方项目启动，但导入时 cwd 是进程级选择。两种默认值都有隐含条件。

**建议做什么：**保留 `load_app_config(path=...)`；有多工作区需求时，让工具构造入口显式接收 workspace_root。

**为什么：**同一个 harness 在不同项目工作时，不应依赖安装位置或先前一次 import 的 cwd。

**接口状态：**显式 config path 两边已有；显式 workspace_root 的工具工厂是建议，两边都没有实现。不要把 copy 的源码目录策略直接迁移到已安装包。

**验收：**从不同目录启动但指定相同配置／工作区，工具访问范围一致；两个不同工作区的工具集合互不影响。两边 bash 的 cwd 都只是执行目录，不是 sandbox。

来源：[当前配置](../packages/harness/shikigen/app_config.py:9)、[copy 配置](../../shikigen-agent-copy/harness/app_config.py:9)、[当前文件工具](../packages/harness/shikigen/tools/filesystem.py:7)、[copy 文件工具](../../shikigen-agent-copy/tools/filesystem.py:7)。

## 4. 需要修的地方：迁移前不能忽略的缺口

### 4.1 copy 跨 Run 的旧历史可能被重复归入新 Run

**证据：局部行为已复现，完整数据库／HTTP 场景未验证。**

`_start_product_invocation()` 每次新建 Adapter，仅用本次入口消息初始化其已见消息集合。随后 `adapt_root_values()` 遍历完整 messages 快照，把未在本 invocation 见过的消息都产出为候选。`append_message()` 的幂等查询则限定在当前 Run 内。

本次局部复现：先用 `new-human` 初始化 Adapter，再提供 `[old-human, old-ai, new-human]` 快照，输出候选是 `['old-human', 'old-ai']`。

因此，当恢复的 root values 包含上一 Run 的历史时，旧消息会成为写入新 Run 的候选；当前去重范围不能阻止这种归属错误。迁移前必须定义“历史基线”或“本轮新消息”的判断依据。不能仅用一个每次调用清空的 set 解决跨 Run 归属。

还应补齐同一个有 checkpoint 的 Thread 连续发起两个真实 Run 的测试；已有多终态历史重建测试主要直接构造数据库记录，不能代替这项验证。

来源：[Adapter 初始化与调用](../../shikigen-agent-copy/server/product_run.py:295)、[全量快照提取](../../shikigen-agent-copy/server/langgraph_event_adapter.py:159)、[按 Run 查重](../../shikigen-agent-copy/server/persistence/run_persistence.py:713)、[已有终态重建测试](../../shikigen-agent-copy/tests/test_product_run_sse.py:1212)。

### 4.2 copy 的 Thread busy 数据库冲突没有在创建入口转换成 409

**证据：源码推断，未做 HTTP 复现。**

copy 的唯一索引能阻止第二个未终态 Run，但 `_stream_product_run()` 直接调用 `persistence.create_run()`，该方法回滚后原样抛错；当前没有看到这条创建路径把唯一约束冲突映射为 HTTP 409。ThreadGuard 只负责串行化，不能让已存在的 Run 自动结束。

当前项目在 `run_manager.create()` 报 busy 时显式返回 409。迁移数据库排他时，应保留这个调用方可理解的错误语义。

来源：[copy 创建路由](../../shikigen-agent-copy/server/routes/runs.py:299)、[copy 创建事务](../../shikigen-agent-copy/server/persistence/run_persistence.py:287)、[当前 busy 处理](../app/routes/run.py)。

### 4.3 copy 的取消结果没有直接广播到已有内容流

**证据：源码事实；是否影响具体客户端取决于重连策略。**

取消路由提交 `cancel_run()` 后请求停止 handle，没有把返回的持久取消事件 publish 给现有订阅。执行 finally 关闭 stream 后，订阅者可能先看到 EOF，需要重新 GET 才拿到 cancelled 事实。copy 客户端包含断流后的重连／状态收敛逻辑。

若只迁移服务端，需要明确“取消是推送终态”还是“关闭流后客户端查询”，不能沿用当前消费者对最后一个事件必为终态的假设。

来源：[取消 HTTP 路径](../../shikigen-agent-copy/server/routes/runs.py:104)、[执行 finally](../../shikigen-agent-copy/server/product_run.py)、[客户端流消费与重连](../../shikigen-agent-copy/packages/react-client/src/effects/store.ts:466)。

### 4.4 包结构与依赖不能反向照搬

copy 的 `packages/harness/pyproject.toml` 指定 wheel 包目录为 `src/shikigen_agent`，但实际新目录是 `packages/harness/shikigen/`，其中 `__init__.py` 为空；主要实现仍在根目录 harness/tools/middleware。根项目也没有当前项目的 uv workspace 连接配置。

应迁移行为和接口到当前包，而不是把文件路径和旧 import 一起复制回来。copy 同时保留 `harness/loop.py`、`RunManager` 和 server 产品执行路径，不能把两套生命周期都作为新应用的必经流程。

来源：[copy 子包配置](../../shikigen-agent-copy/packages/harness/pyproject.toml)、[copy 根配置](../../shikigen-agent-copy/pyproject.toml)、[当前 workspace](../pyproject.toml)。

### 4.5 数据库格式切换与跨存储一致性

当前消息记录和 checkpoint 使用同一路径的数据库，但经不同连接操作，也没有跨两者的统一事务。copy 将产品数据库拆为 `product-v1.db`，checkpoint 保留在 `shikigen.db`；产品表增加审批、使用量和序号分配记录，并删除 Thread 的 user_id/title 字段。

copy `RunPersistence.open()` 严格比较 schema，遇到旧格式直接拒绝，不执行旧 ChatStore 数据迁移。因此需要单独设计旧数据转换和回滚方案，不能把存储类替换视为无损升级。

产品事务原子也不代表 checkpoint、产品历史和外部工具副作用三者原子。当前 copy 通过恢复校验处理部分不一致，尚未提供通用崩溃后自动续跑。

来源：[当前启动存储](../app/server.py)、[copy 数据库路径](../../shikigen-agent-copy/server/config.py)、[copy schema 检查](../../shikigen-agent-copy/server/persistence/run_persistence.py:224)。

### 4.6 两边共有的长时运行限制

- 内存事件缓存与订阅队列无界；长 invocation、大工具结果、慢观察者会增加内存占用。copy 已有缓存优化备忘，但代码尚未实现限制和裁剪。
- copy 的 `ThreadGuard` 用字典缓存每个 Thread 的 Lock，没有回收机制；长期服务应评估 Thread 数量增长。
- copy 的 ActiveRunRegistry 是进程内注册表。不能由本进程“没有 handle”推断其他进程也没有执行。
- Adapter 消费所有 namespace 的消息增量，而完整历史只从 root values 提取；子图消息若没有进入父图状态，需明确它是仅展示信息，还是也应可恢复。不要宣称现有实现覆盖所有子 Agent 独立历史。
- CONTEXT 中定义了 Active Run Silence，但本次未在 server/harness 中找到相应活动计时和监测实现。术语和待办文档不等于功能已经落地。

来源：[缓存取舍备忘](../../shikigen-agent-copy/docs/invocation-replay-cache-optimization.md)、[ThreadGuard](../../shikigen-agent-copy/server/composition.py:27)、[copy 执行事件循环](../../shikigen-agent-copy/server/product_run.py)、[领域定义](../../shikigen-agent-copy/CONTEXT.md)。

## 5. 值得讨论的迁移顺序

以下是实现建议，不限制自行扩展测试、同步版本或文档。每一步都应保持当前应用可运行。

| 优先级 | 任务 | 原因 | 最小验收 |
| --- | --- | --- | --- |
| P0 | 修复未开始迭代的订阅清理 | 已复现的资源管理缺口，范围小 | 关闭后订阅集合恢复为空 |
| P0 | 完整终态先落库再发布 | 避免已展示完成、数据库仍 running | 模拟存储失败，不推送成功 |
| P1 | 显式 Checkpointer 与子 Agent 工具集合 | 小接口改动，练习依赖注入与能力组合 | 无存储可运行，子集合不修改父集合 |
| P1 | Run 状态与进程内 handle 分离 | 为暂停、多次恢复提供稳定任务身份 | 清理 handle 不删除持久任务 |
| P1 | 原子业务操作、数据库排他、冲突检测 | 将一致性责任集中到存储接口 | 重复消息幂等，冲突可见，busy 返回 409 |
| P1 | 统一消息身份和转换 | 为实时与历史共用模型打基础 | 连续两个 Run 不复制旧历史 |
| P2 | 预留 seq、完整重建与 live 拼接 | 解决真实重连需求 | 刷新不重启 Graph，不重不漏 |
| P2 | 严格协议模型和共享 fixture | 保证不同消费者解释一致 | 生成契约无漂移，完整结果替换预览 |
| P2 | 持久 Run 使用量累加 | 多次 invocation 共用 Run 时有正确统计位置 | 两次执行累计；取消／错误仍记录可获得用量 |
| P3 | 审批事务、取消、同 Run resume | 依赖上述身份和持久状态 | 重复审批只接受一次，旧审批不能恢复新暂停 |
| P3 | 启动状态恢复检查 | 处理实际进程丢失 | 临时不可用与永久损坏分开 |

暂不把 React UI、SSE 替换、通用 JSON 路径补丁、多 worker、自动崩溃续跑作为前置任务。它们可以在有明确需求时继续设计。

## 6. 推荐迁移的测试思想

copy 最有价值的测试不是数量，而是围绕可观察场景定义正确性：

1. **确定性真实 Graph。**不用真实模型也能产生父图／子图事件、多 Interrupt 和重复暂停，检查框架投影是否符合应用假设。
2. **事务竞争。**同时提交两份审批、审批与取消竞争，检查最终事实和 resume 次数。
3. **观察连接独立。**断线后 Graph 继续执行；重新读取接上实时输出；一位观察者退出不影响其他人。
4. **崩溃窗口。**事务未提交、审批已接受但尚未恢复、恢复已经开始三个阶段退出进程，分别验证持久状态。
5. **生产者与消费者共用 fixture。**同一事件样本经 Python 契约验证和客户端投影，不只检查字段类型。
6. **模块独立性。**阻断 server import 后 harness 仍可导入；当前项目还应保留已安装包在仓库外可导入的测试。

迁移时应另外补上：同 Thread 跨 Run 历史归属、已有 Run busy 的 HTTP 错误映射、取消后其他订阅者如何获知终态、usage 与完成通知的时序。这些不能从测试文件数量推断已覆盖。

来源：[确定性 Graph fixture](../../shikigen-agent-copy/tests/fixtures/deterministic_graph.py)、[产品流测试](../../shikigen-agent-copy/tests/test_product_run_sse.py)、[恢复与进程崩溃测试](../../shikigen-agent-copy/tests/test_recovery.py)、[契约测试](../../shikigen-agent-copy/tests/test_sse_contract.py)、[当前包导入测试](../tests/test_package_imports.py)。

## 7. 本次验证记录

所有测试使用目录中现有 `.venv/bin/python`，设置 `PYTHONDONTWRITEBYTECODE=1`；未安装依赖、未启动真实服务、未请求外部模型。没有修改代码、测试、Git index 或提交。

| 对象 | 测试模块／方式 | 结果 |
| --- | --- | --- |
| 当前项目 | `tests.test_stream tests.test_loop tests.test_run_manager tests.test_package_imports` | 20 个通过 |
| copy | `tests.test_langgraph_event_adapter tests.test_sse_contract tests.test_agent_independence tests.test_tool_capability_composition` | 29 个通过 |
| copy | `tests.test_stream tests.test_deterministic_graph_fixture` | 8 个通过 |
| copy | `tests.test_run_persistence`，25 秒超时保护 | 首个用例未完成，退出码 124；原因未确认，不能记为通过或断言失败 |
| 当前项目 | 创建 Stream 订阅，未迭代即 aclose，检查订阅集合 | 关闭前 1，关闭后仍为 1，复现清理缺口 |
| copy | Adapter 仅初始化新 HumanMessage，再输入含旧历史的 root values | 旧 Human/AI 消息被产出为候选，确认跨 Run 基线缺口的局部行为 |

本轮总计 **57 个测试通过**。数据库持久化、完整 HTTP 审批恢复与崩溃测试尚未完成验证；阅读这些测试只证明它们存在相应验收场景。没有运行 React 客户端测试，没有实际构建 copy wheel。

本次临时测试日志在 `/tmp/shikigen-current-runtime-tests.log`、`/tmp/shikigen-copy-contract-tests.log`、`/tmp/shikigen-copy-stream-fixture-tests.log` 和 `/tmp/shikigen-copy-persistence-tests.log`。临时目录可能被清理，因此以上结果已在本文留档。
