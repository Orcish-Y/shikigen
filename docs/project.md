# 项目开发参考

更新：2026-09-24。Run 迁移第 1—8 步已完成：持久化、消息归属、只读重建、审批恢复、取消、用量累计与启动恢复均已接通。
运行方式见[项目 README](../README.md)，设计调查见[research/](research/README.md)。本文统一归档原 `docs/project/` 下的分支比较、迁移清单、4A 存储契约和第 5 步消息契约，按当前实现整理，字段细节以代码和测试为准。历史建议不再作为当前待办；阶段验收与尚未闭环的问题保留在文末。

## 架构与入口

产品 Run 表示一次用户任务，可跨多次 Graph 调用；RunExecution 表示进程内的一次执行。
观察连接独立管理，断线仅释放订阅，执行继续。

| 模块 | 职责与 API |
| --- | --- |
| [装配](../packages/harness/shikigen/runtime/composition.py) | `open_runtime()` 装配依赖、启动恢复并管理关闭；HTTP / Python / CLI 共用 |
| [Run 服务](../packages/harness/shikigen/runtime/runs.py) | `RunService` 创建、等待、查询、观察、恢复、取消；`RunTransitions` 决定事务内状态转换 |
| [Graph 适配](../packages/harness/shikigen/core/graph_events.py) | `GraphEventAdapter` 转换根图预览与完整消息候选，不访问存储 |
| [事件接入](../packages/harness/shikigen/runtime/run_events.py) | `RunEventIngestor` 预留 seq、接入消息并在提交后发布 |
| [存储](../packages/harness/shikigen/persistence/chat_store.py) | `ChatStore.transaction()` 与组合 stores 负责事务、约束和查询 |
| [HTTP](../app/routes/run.py) / [SSE](../app/run_contract.py) | 请求校验、错误映射、编码和订阅释放，不自行编排 Graph 或事务 |

harness 不依赖 app 或 FastAPI。完整消息沿 Loop → Adapter → Ingestor 接入，不使用持久化 middleware。
checkpoint 由 Graph 与注入的 saver 管理；工厂不隐式创建 checkpointer，主／子 Agent 工具集合可分别配置。

`create_lead_agent(checkpointer=None)` 不创建默认存储。`task_tool_registry` 缺省／None
沿用主工具集合，显式空集合保持为空；`excluding()` 返回新容器但共享工具实例。
工具白名单／排除策略由应用配置决定，通用 task 仅另外禁止递归 task。
仅排除 write_file、bash 不代表后来加入的 MCP 工具也受到副作用限制。

## 运行接口与资源生命周期

**做什么：**HTTP、普通 Python 和模块入口共用 Run 服务；产品状态与本地 Task、Stream 分离。
**为什么：**暂停会结束本次 Graph 调用，但不会结束产品任务；观察连接关闭也不能取消任务。
**API：**通过 `open_runtime(config)` 管理资源，再调用 `runtime.threads` 和 `runtime.runs`。

| 操作 | 共享接口 | 语义 |
| --- | --- | --- |
| 创建会话 | `threads.create_thread()` | 返回 Thread 身份 |
| 开始任务 | `runs.start_run(thread_id, message)` | 创建事务提交后启动执行，返回 RunExecution |
| 等待执行 | `runs.wait_run(execution)` | 等待本次执行和持久化收尾；暂停返回 interrupted，不等待未来人工审批 |
| 查询任务 | `runs.read_run(thread_id, run_id)` | 读取持久快照；暂停状态会在 Thread 锁内再次校验 |
| 读取历史 | `runs.list_run_messages()` / `list_run_events()` | 返回已提交消息或全部事实 |
| 观察任务 | `runs.observe_run(thread_id, run_id)` | 返回只读 RunObservation，不启动 Graph |
| 审批恢复 | `runs.resume_run(thread_id, run_id, responses)` | 返回新的执行对象，沿用原 run_id |
| 取消任务 | `runs.cancel_run(thread_id, run_id)` | 返回已提交 RunSnapshot，不等同于工具副作用已经停止 |

启动时先完成恢复扫描，再交付 Runtime；关闭时先收尾执行资源，再释放存储和 checkpointer。
创建、恢复、取消共用 Thread 协调，已接受的后台操作由应用生命周期持有，请求断开不会撤销操作。
观察方在 `finally` 中调用 `await observation.aclose()` 或 `await subscription.aclose()`；
即使未开始迭代也能释放注册，重复关闭安全。单个订阅不支持与进行中的 `anext()` 并发关闭。

最小无 HTTP 入口为 `python -m shikigen.runtime --config config.json '你好'`，
可用 `--thread-id` 沿用会话；依赖安装、环境变量和存储路径见 README。

## 关键约定

- **状态与事务**：每个 Thread 最多一个非终态 Run；running、interrupted 都占用名额。业务状态与相关事实原子提交后才发布，观察失败不改变已提交状态。
- **消息归属**：Thread 内稳定消息身份唯一；重放保留原 Run、seq 和时间，内容或 metadata 冲突显式报错。不增加调用前 checkpoint baseline。身份模型见 [messages.py](../packages/harness/shikigen/contracts/messages.py)。
- **审批恢复**：保存准确 checkpoint 坐标及全部 Interrupt，不回退到最新 checkpoint。响应精确覆盖当前请求，只支持 approve/reject；resolved 与 running 提交后才恢复同一个 Run。旧 Task 收尾后再安装新执行，旧审批和旧 invocation 不能影响新执行。
- **取消竞争**：先提交 cancelled 再请求停止执行；暂停取消同时使审批失效。先提交的有效终态获胜，迟到结果不得覆盖；取消不保证工具外部副作用已停止。
- **用量**：每次执行独立采集，按本次 running 事实 seq 幂等累计。自然完成／暂停／错误与已知用量一起提交；取消用量可在清理后补交，`wait_run()` 等待收尾。`usage_pending=false` 不保证供应商计费完整，崩溃未知用量不补零。
- **兼容范围**：历史库已放弃，无迁移、旧库检查或 schema marker；无 JSONL、协议版本切换，`event_version` 不升级。

## 持久化数据与业务事务

**做什么：**将业务检查与写入放进同一个事务，调用方只消费已提交返回值。
**为什么：**先在 Service 检查 Thread 是否忙、再单独创建 Run，会留下竞争窗口。
**API：**`RunTransitions` 驱动业务转换，`ChatStore.transaction()` 与组合 stores 执行读写。

### 数据与返回模型

模型定义见 [runs.py](../packages/harness/shikigen/contracts/runs.py)。

| 数据 | 关键字段与约束 |
| --- | --- |
| Thread | id、user_id、title、created_at、updated_at |
| RunSnapshot | id、thread_id、status、error、error_code、时间字段、usage、usage_pending |
| CommittedEvent | id、thread_id、run_id、seq、event_type、category、event_key、content、metadata、created_at |
| RunWriteResult | 已提交 Run 快照与创建事件 |
| EventWriteResult | 完整事件与 inserted，区分新增和重放 |
| CommittedRunState | 实际结算状态、错误、事件、changed 和累计 usage |

数据库用部分唯一索引保护每个 Thread 至多一个 running/interrupted Run，
CHECK 保护状态值和终态时间关系，组合外键保护事件的 Thread/Run 归属。
暂停不填写 completed_at；当前没有 pending Run 状态。
消息和生命周期、审批事实共用 run_events；Thread 消息唯一约束防止重复归属。
thread_sequences 分配序号，message_sequences 保存预留身份；run_usage 保存每次执行结算。

### 操作契约

- **创建：**`RunTransitions.create_run()` 原子保存 running Run、running 事实、入口 HumanMessage 和 Thread 更新时间。不是请求幂等接口；重发请求不能默认返回原 Run。
- **完整消息：**`append_message()` / `append_committed_event()` 保存完整事实，返回 EventWriteResult；相同身份、内容和 metadata 返回原事实，否则 MessageConflict。公开消息追加接口不能自行写入生命周期事实。
- **结算：**`settle_execution()` 原子保存状态、相关事实和已知用量。使用本次 running 事实 seq 识别执行，旧执行不得结算恢复后的新执行；返回结果可能与候选 outcome 不同，发布方必须服从提交结果。
- **读取：**`ChatStore.get_run(run_id, thread_id)` 不存在返回 None，Service 转换成 RunNotFound；事件按 seq 返回。同连接读取等待写锁，避免暴露未提交状态。
- **失败：**事务失败或事务内取消整体回滚。ThreadBusy 与一般 StorageConflict 区分；不能把 Run ID 冲突误报成 Thread 忙。
- **发布：**RunEventIngestor 广播存储返回的完整 durable_event，不重新拼造事实；按事实身份去重。提交后广播失败记录观察错误，可从存储补读，不回滚已提交状态；没有跨进程可靠投递或自动补发。

持久 JSON 严格序列化，不将非法对象或 NaN 转成字符串。对象键顺序不构成冲突，
数组顺序、类型、完整 payload 和 metadata 的变化构成冲突；生成的行 ID、seq、时间不参与内容比较。

## 消息身份与完整内容

**做什么：**用稳定身份连接预览、完整消息和 checkpoint 重放。
**为什么：**框架恢复时会带回旧历史，不能把本次首次看到的消息都归到当前 Run。
**API：**[messages.py](../packages/harness/shikigen/contracts/messages.py) 的转换与校验、GraphEventAdapter、RunEventIngestor 和存储唯一约束。

| 身份 | 含义与范围 |
| --- | --- |
| run_id | 产品任务归属，审批恢复沿用 |
| Human/AI message_id | 非空稳定消息身份 |
| tool_call_id | 工具调用身份，同 Thread 不得用于不同调用 |
| Tool message_id | 固定为 `tool-result:{tool_call_id}`，忽略框架临时 ID |
| event_key | `human:{id}`、`ai:{id}`、`tool:{tool_call_id}`，消息在 Thread 内按类型唯一 |
| seq | Thread 内顺序，预览预留、完整事实复用 |
| 内存流 id | 当前内存流顺序，不是持久游标，也不输出为 SSE id |

入口消息由创建事务保存。Loop 顺序消费原始 Graph 事件，Adapter 从根 namespace 的
messages 提取文本预览、从根图 values 提取完整消息；Ingestor 提交后发布。
Adapter 过滤执行内重复快照，数据库负责跨 Run 和恢复后的最终归属。

同身份同内容重放保留原 run_id、seq、时间，同 Run 或跨 Run 均不重复广播；
同身份内容变化报错。新 Run 重用旧入口 ID 会让创建事务失败，不留下半个 Run。
完整消息已提交后再到达其增量属于协议错误；预览与最终文本不同仅记录诊断，最终事实优先。

AI 消息保留 tool_calls；工具结果保留 tool_call_id、name、status 和可选 artifact。
artifact 省略与显式 null 不同，必须是 JSON 值。content 支持文本或字符串／JSON 对象组成的
block 数组，保留原内容，不负责解释图片、音频和厂商专用 block 的展示语义。
子 Agent 内部对话不写入父 Run；返回父图 messages 的工具结果属于父 Run。

## 消息与观察

SSE 仅有 `metadata`（归属、状态与用量）、`delta`（预览）、`event`（已提交事实）、`error`（观察失败）。
完整事实分 message、lifecycle、approval；内部 durable_event 投影为 SSE event。

预览与完整消息共用 seq，完整事实覆盖同 seq 预览；允许空洞，seq 不是提交水位或增量游标。
`POST /api/threads/{thread_id}/stream` 创建任务；`GET /api/threads/{thread_id}/runs/{run_id}/stream` 只重建并跟随，不调用 Graph。
每次重连新建客户端投影；没有 SSE id、Last-Event-ID 或增量续传。EOF 不代表任务成功。
Python 使用 `observe_run()`，退出时 `aclose()`；暂停流不会自动随 resume 重新打开。

### SSE 契约与 HTTP 入口

| 帧 | 主要字段 |
| --- | --- |
| metadata | thread_id、run_id、status，可携带 usage、usage_pending |
| delta | seq、message_id、field、value；当前 Loop 发布 content，契约允许 reasoning |
| event | seq、created_at、category、event_type、payload |
| error | code、message、recoverable；仅表示观察失败 |

message 事实使用 event_type=created，lifecycle 使用 status_changed；approval 使用
required、resolved、invalidated。任务执行失败属于 lifecycle，不是观察 error。
未知结构字段、事件或错误类型被拒绝；content block、工具输入、artifact、metadata 内部 JSON 可扩展。
省略字段不自动补 null。编码校验失败输出 invalid_event 并结束该订阅，不影响 Run 执行；
recoverable 表示可查询已持久事实，不承诺自动续接。

以下路径均相对于 `/api/threads/{thread_id}`：

| HTTP | 行为 |
| --- | --- |
| POST /stream | 创建 Run 并返回 SSE |
| GET /runs/{run_id}/stream | 重建已有 Run 并按需跟随 |
| GET /messages、GET /runs/{run_id}/messages | 查询完整消息 |
| POST /runs/{run_id}/approval-decisions | 接受审批，返回恢复执行的 SSE |
| POST /runs/{run_id}/cancel | 无请求体，返回 `200 {"data": RunSnapshot}` |

归属不存在返回 404，忙／冲突返回 409，审批响应格式或动作非法返回 422，
观察或 checkpoint 临时不可用返回可重试 503。重连入口拒绝查询参数和 Last-Event-ID，返回 400。
POST SSE 使用 fetch 流读取，不能直接用原生 EventSource；Content-Type 为 text/event-stream，
每帧以空行分隔，JSON 字符串换行必须转义。

### 历史与实时拼接

活跃执行先同步订阅，再读取本次 invocation 起点之前的持久前缀，随后交付该执行缓存和实时事件。
不以查询时最大 seq 切分，因为较小的预留序号可能稍后才提交。resume 的缓存从本次 resolved 起开始。
读取期间执行完成或注册表移除句柄，已有订阅仍能交付结果；终态／暂停可直接从数据库重建。
running 无本地执行时，观察接口返回可重试 503，不创建 Graph；启动扫描按后文规则收敛状态。

## 审批、取消与累计用量

### 暂停与同 Run 恢复

默认主 Agent 对 write_file、bash 使用 approve/reject 审批。GraphPauseCollector 从根 checkpoint
锁定准确坐标，收集父／子图全部 Interrupt；settle_execution 同一事务保存 required 与 interrupted。
暂停仍占用 Thread，既有 GET 流可在没有执行句柄时重建请求。

responses 的键必须准确覆盖全部 Interrupt ID；每个 decisions 数组按 action_requests 顺序对应，
数量、动作及 review_configs 都要匹配。同名工具的多次调用分别处理；reject 可带 message，
不接受 edit/respond。恢复前精确读取保存的 checkpoint，不回退到最新 checkpoint。

接受审批事务再次检查当前 pending 请求，原子写入 resolved 和 running，提交后才通过
Command(resume=...) 恢复原 run_id。等待旧 Task 收尾后安装新资源，支持连续暂停。
重复或旧响应冲突；事务失败不消费审批。接受后 Task 启动失败保留 resolved 并尝试记录
resume_start_failed；接受后进程崩溃则由启动恢复处理为 invocation_lost。
请求失败或断开不代表服务器未接受，调用方应重建已有 Run 查询事实。

### 取消竞争

| 首次有效提交 | 最终语义 |
| --- | --- |
| 取消先于审批 | cancelled，审批冲突，不恢复 Graph |
| 审批先于取消 | resolved → running → cancelled，停止恢复后的执行 |
| 正常完成先于取消 | 保留 completed，取消返回已有状态 |
| 取消先于迟到完成／失败／暂停 | 保留 cancelled，不写相反终态或新审批 |

暂停取消在同一事务写 invalidated 与 cancelled。取消、执行结算、事实发布和关闭进行本地协调，
提交并发布后才请求停止。新 Run 等旧执行清理，避免并发操作同一 checkpoint。
无执行句柄也可持久取消；已关闭的暂停流不重新打开，调用方重建 GET 流读取结果。

### 用量结算

每次 invocation 独立 tracker，主模型、Goal evaluator 与子 Agent 继承 callbacks，
不额外挂第二个 tracker 或遍历消息再次累计。run_usage 用 `(thread_id, run_id, invocation_seq)`
作为幂等键，invocation_seq 复用 running 事实 seq；同键同内容不重复累计，内容不同报冲突。
查询汇总 input/output/tokens、calls 和 by_model。

未结算时 usage 为 null；resume 后 usage_pending 重新为 true，已累计值仍保留。
自然完成、暂停、错误通知到达时，本次已知用量已与状态一起提交。取消通知可能先到，
Graph 清理后补交用量；wait_run 等待收尾。未报告的模型用量和崩溃前仅在内存中的统计无法恢复。
usage_pending=false 仅表示各次执行已知用量已保存；calls 是收到完成回调的次数，不是准确计费凭证。
用量事务失败会报告 run_persistence_failed 并记录堆栈，不发布未提交的 usage 或成功终态。

## 启动恢复与能力边界

[恢复协调器](../packages/harness/shikigen/runtime/recovery.py) 在 Runtime 接受操作前扫描，查询／恢复暂停时再次校验：

| 情况 | 处理 |
| --- | --- |
| 终态，或 running 有本地执行 | 保持原状 |
| running 无本地执行 | error / invocation_lost，不自动重放工具；包含审批已接受后崩溃 |
| interrupted 与准确 checkpoint 匹配 | 保留，允许继续审批 |
| 暂停事实缺失、不一致或 JSON 损坏 | error / approval_state_corrupt；原损坏内容保留，历史读取仍可能失败 |
| 可恢复存储故障 | 保留状态，启动重试；请求返回可重试错误 |
| SQL／表结构错误或未知程序异常 | 记录堆栈并抛出，不无限重试 |

恢复写入复查状态，不能覆盖并发终态，重复扫描不重复追加错误。
当前仅支持单进程执行归属；产品库、checkpoint 与工具副作用没有跨系统事务。
缓存和订阅队列尚未限容量。子 Agent 不自动继承主 Agent 审批策略，无独立子 Run 历史；工具过滤不等于文件系统隔离。

## 数据与协议切换

历史产品数据库直接放弃，不提供旧库读取、迁移、schema marker 或自动清理。
部署新版前由部署者删除旧库并从当前 schema 新建；文档整理不操作实际数据库。
HTTP 已由 JSONL 改为 SSE，删除 output_index、旧完成事件及 v2 版本切换代码，event_version 不升级。
旧消费者需按上述四类帧与完整事实投影适配；不保留旧协议开关。

## 后续任务

### 迁移收尾

- [ ] 查明最初 copy 项目 tests.test_run_persistence 首例超时原因。第 3 步曾复现沙箱内最小 aiosqlite 连接卡住、沙箱外正常，但不能据此认定原超时根因相同；该用例不作为当前迁移通过依据。
- [ ] 核查旧 core/loop.py 的 RunRecord 入口及 core/run_manager.py 的调用方，确认兼容用途后再决定保留或删除。应用已走共享 runtime，库内旧入口存在不等于应用有两条产品执行链路。

### 后续扩展

这些需求不阻塞本次迁移完成。

- [ ] 显式 `workspace_root`：工具工厂接收路径，替代导入时 cwd／源码路径假设。
- [ ] 内存与慢消费者限制：确定缓存、工具输出、订阅队列的容量和超限行为。
- [ ] 增量重连：先定义提交进度与缓存裁剪关系，再提供 cursor。
- [ ] 多 worker：先实现执行 owner、租约和跨进程事件传递，再调整执行丢失判断。
- [ ] 崩溃自动续跑：先定义恢复意图、可重放节点和工具副作用幂等。
- [ ] 后台子 Agent：定义独立身份、历史、通信、取消和恢复；当前 task 等待子 Agent 返回。

## 验证入口

最近代码验收记录：2026-09-23，227 项测试通过，类型检查及受影响文件 Ruff 检查通过；本次文档合并未重跑业务测试。
[tests/](../tests/) 中重点参考 `test_storage_contracts`、`test_message_contract`、`test_message_sequence`、
`test_run_observation`、`test_approval_pause`、`test_approval_resume`、`test_run_cancel`、`test_run_usage`、`test_recovery`。
`runtime_no_http.py` 与 `recovery_process.py` 覆盖无 HTTP 运行和真实进程崩溃。

```bash
uv run python -m unittest discover -s tests
uv run ty check app packages/harness
```

## 迁移决策与阶段归档

最初比较日期为 2026-09-11：当前项目 master 的 HEAD 为
`2644b37f2951fa87dfe46b9e93cac184b21aab8d`，copy 项目 260904 的 HEAD 为
`edbc56fa522f3b61a17a8eda04dd50e2dca27527`；比较还包含 copy 当时未提交内容，
不能仅用两个提交的 diff 代表调查，也不能把历史分支状态当作当前状态。

保留当前 uv workspace 与可安装 harness 包，吸收 copy 的持久 Run、原子业务事务、
重建和审批恢复设计。没有整套照搬 copy：跨 Run 归属、Thread busy 冲突映射、
取消广播和完成前用量结算都需要按当前契约补齐。
模型创建、MCP 加载、web 工具、GoalMiddleware、task 工具和 TokenTracker 算法并非此次新增能力。
Goal 的 Graph 内续跑也不等于跨进程长时调度器，task 等待返回不等于后台委派。

| 阶段 | 完成结果与历史验收 |
| --- | --- |
| 第 1、2 步，09-15 | 订阅可靠关闭；checkpointer 与主／子工具集合由调用者决定。81 项相关测试及另 8 项执行兼容测试通过 |
| 第 3 步，09-15 | 持久 Run 与执行资源分离，HTTP／Python 共享 runtime；140 项全量测试通过 |
| 第 4A 步，09-15 | 新库约束、消息冲突、事务返回完整已提交事实 |
| 第 4B／4C 步，09-16 | 明确放弃历史库；统一提交后发布，区分事务失败与广播失败 |
| 第 4D 步 | 最小 Python 入口、无 HTTP 独立进程执行／查询／释放验收完成 |
| 第 5 步，09-17 | 消息身份、跨 Run 归属和严格事件契约；166 项全量测试通过 |
| 第 6A 与入口调整，09-18 | SSE、seq 预留与复用；完整消息改由 Graph Adapter 接入，删除持久化 middleware；最终记录 171 项通过 |
| 第 6B 步，09-21 | 全量重建与实时跟随，无 HTTP 同样可用，重连不增加模型调用 |
| 第 7A／7B 步，09-22 | 持久审批与同 Run 多次恢复，包含父子图及并发响应；7B 全量 198 项通过 |
| 第 7C 步，09-22 | 取消竞争、无句柄取消与持久广播；206 项全量测试通过 |
| 第 7D 步，09-22 | 幂等累计用量、回调传播及通知时序；215 项全量测试通过 |
| 第 8 步，09-23 | 启动恢复、真实进程崩溃矩阵与异常分类；复核后 227 项全量测试通过 |

以上是各阶段验收记录，数量不相加；早期通过项不替代最终回归，也不表示本次重新执行。
原始比较的 57 项通过与 copy 持久化测试 25 秒超时保留为历史背景，未闭环原因见迁移收尾。
历史 Adapter baseline、持久化 middleware、旧库迁移和协议 v2 方案均不再作为当前实施方案。

### 关键故障验收矩阵

| 场景 | 应有结果 |
| --- | --- |
| 创建事务中途退出 | 不存在半个 Run 或孤立入口消息 |
| Run 已提交，Task 尚未启动便退出 | invocation_lost，入口消息不重复 |
| 完成已提交，尚未发布便退出 | 从历史重建 completed |
| 审批事务未提交便退出 | 保留完整 interrupted 与 pending 审批 |
| 审批接受后、恢复启动前退出 | 保留 resolved，按 running 收敛 invocation_lost |
| resume 执行中工具已产生副作用后退出 | 不自动重放工具；尚无新暂停或终态时为 invocation_lost |
| 暂停 checkpoint 暂时不可读 | 保留原状态，可取消地重试 |
| 暂停事实或 checkpoint 永久损坏 | 原子写 approval_state_corrupt，继续检查其他 Run |
| 历史读取期间发布／完成／移除句柄 | 订阅交付完整结果，无遗漏、重复或新 Graph 调用 |
| 两连接竞争创建／审批／取消 | 事务决定唯一有效结果，迟到写入不覆盖 |

恢复矩阵使用真实 SQLite 和独立子进程在明确同步点退出；重复扫描检查状态与事实幂等。
未调用外部模型、真实 MCP／网络服务，未验证 React 客户端；产品库、checkpoint 与外部副作用
没有跨系统原子性保证。copy 的活动静默监测术语和缓存优化备忘不代表当前已有对应功能。

后续修改的 review 材料应说明完成项、接口契约、正常与失败／竞争路径、实际测试及未验证范围，
并确认应用只走一条执行／持久化链路。建议顺序仍为做得好的、需要修的、值得讨论的。

设计背景可查阅[持久化职责调查](research/agent-persistence-ownership-research.md)、
[运行边界对照](research/agent-runtime-boundary-comparison.md)和[研究索引](research/README.md)。
