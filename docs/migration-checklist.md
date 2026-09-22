# 设计迁移实施清单

日期：2026-09-11。

2026-09-16 策略调整：历史产品数据库内容直接放弃，不做旧库迁移或兼容读取。当前
`ChatStore` 只在新数据库上安装当前 schema；历史数据库不在支持范围内，部署者需要先删除旧数据库再创建新库。`event_version` 暂不升级，HTTP 已于 2026-09-18 切换 SSE；事件
v2 模型、版本切换和对应兼容代码已删除。下面早先关于 4B 迁移和 5B v2 的记录以本说明为准。

2026-09-14 补充：将“不启动 FastAPI 也能运行完整 Run 流程”纳入本次迁移，在第 3、4 步完成基础入口，第 6—8 步同步覆盖后续能力。新增任务保持待完成，不代表现有编排骨架已经实现该目标。

本文把 [两个工作目录的差异分析](branch-comparison-and-migration.md) 展开为可以逐项实现、验收的工作清单。这里列的是建议方案和待完成任务，不代表代码已经修改，也不新增工作区协作约定。

目标：保留当前可安装的 `shikigen-harness` 包，逐步吸收 copy 项目在持久 Run、事件一致性、重连、审批和恢复方面的设计；同一套运行模块必须支持 HTTP 和无 HTTP 的 Python 入口，包含执行、持久化及资源生命周期。代码由你实现，这份清单用于确定任务、解释接口和后续 review。

任务完成后要修改本文案，记录结果以及勾选相关选项

## 一、先理解迁移后的职责分工

用户的一次任务可以跨越多次 Graph 调用。网络连接可能断开，Graph 调用可能因为审批而结束，但用户任务仍然存在。因此，需要分别回答三个问题：

1. **任务现在是什么状态？**由持久化产品 Run 回答。
2. **当前进程正在执行什么？**由本地执行对象 `RunExecution` 回答。
3. **观察者看到了什么？**由历史读取与实时订阅回答。

它们通过 Run 身份关联，不应共享同一个“是否结束”变量。

| 位置 | 应承担的职责 | 调用方需要知道的接口 |
| --- | --- | --- |
| `packages/harness/shikigen/` 当前执行层 | 创建 Agent、执行 Graph、广播事件，在消息形成与执行边界驱动 journal 和 checkpoint 保存 | Agent 工厂、执行入口、订阅与取消接口、注入的 MessageJournal / checkpointer |
| `app/` 的独立 Run 运行模块 | 接受不同入口的 Run 操作，保留本地执行资源，连接执行与持久化 | 创建、执行、等待、查询、观察、取消、恢复一个 Run |
| `app/runtime.py` | 保存运行配置与已装配依赖的引用，不实现业务方法 | `Runtime` 数据容器，包含 config、存储、执行资源与服务引用 |
| `app/services/` | Thread 创建与查询、产品 Run 的业务编排 | `runtime.threads` 与 `runtime.runs` 中的业务接口 |
| `app/lifecycle.py` | 保留已接收的后台操作，协调停止接收与资源回收 | `ApplicationLifecycle.accept()`、`shutdown()` |
| 协议无关的装配模块 | 打开存储与 checkpointer、创建 Agent 和运行对象，统一启动与关闭 | `open_runtime(config=...)` 异步上下文管理器（建议名称） |
| `app/persistence/` 当前存储实现 | 校验产品状态转换、原子写入完整消息和事件、历史查询；保存时机由执行层或 Run runtime 驱动 | 语义明确的事务操作与可注入存储接口 |
| 应用层事件适配模块 | 将框架消息、checkpoint 转成产品需要的数据 | 转换完整消息、增量与暂停状态 |
| HTTP 路由和编码模块 | 校验请求、鉴权、映射错误、编码 SSE，调用共享运行模块 | 请求模型、读取结果、流响应 |
| 无 HTTP 的 Python 入口 | 进入共享装配上下文，发起 Run 并等待所需执行与收尾 | 与 HTTP 相同的运行接口，不复制事务或 Task 编排 |

职责按“协议适配层 → 独立 Run runtime → 单次 Agent 执行”划分。执行层通过注入的 journal/checkpointer 接口驱动完整消息和执行状态保存；Run runtime 负责 Run 生命周期与持久化编排；具体存储实现负责事务、约束和读写，装配入口负责后端配置及打开关闭。通用 harness 不直接导入 `app`、FastAPI 或具体产品数据库，不等于它不参与持久化。

上述目录是当前组织方式。可复用的 Run 调度、取消、恢复和 RunStore 接口可以纳入 harness/runtime，用户归属等产品语义由产品层承担；harness 不限于单次 Graph 执行。此处 Run runtime 指运行服务与编排能力，不特指 `app/runtime.py` 的数据容器。新的模块文件名可以自行决定，下面出现的新增接口名是设计建议，不要求与 copy 一字不差。依据：[持久化职责调查](agent-persistence-ownership-research.md)、[运行边界对照](agent-runtime-boundary-comparison.md)。

独立运行、装配、存储和内部事件模块也不导入 FastAPI、`app.server` 或 routes，不接收 Request、app.state 或 StreamingResponse。HTTP lifespan 只进入和退出共享装配上下文；普通 Python 调用方直接管理同一上下文。模块可以先留在 `app/`，无需为了脱离 HTTP 全部移入 `agent.py`。本目标保持单进程执行归属，进程退出后的自动续跑仍是后续议题。

## 二、总顺序与里程碑

| 顺序 | 任务 | 前置依赖 | 完成后获得的能力 |
| --- | --- | --- | --- |
| 准备 | 固定基线与明确兼容范围 | 无 | 知道哪些行为必须保留，哪些测试尚未可靠运行 |
| 1 | 订阅正确释放 | 准备 | 消费者退出后不残留队列 |
| 2 | 工厂依赖与子 Agent 工具集合 | 准备 | 可复用的存储和能力配置 |
| 3 | 产品 Run 与本地执行资源拆分、共享运行接口 | 1 | 不依赖 HTTP 的生命周期编排骨架 |
| 4 | 原子持久化、提交后发布与独立运行入口 | 2、3；与 3 同批完成应用切换 | HTTP 与无 HTTP 入口共享可持久运行的实现 |
| 5 | 消息身份、归属与严格契约 | 4 | 实时和历史能准确指向同一条消息 |
| 6 | 完整重建与实时跟随 | 1、4、5 | 刷新和重连不会重复执行任务 |
| 7 | 审批、取消、使用量与同 Run 恢复 | 3—6 | 一个用户任务跨多次执行继续推进 |
| 8 | 启动恢复与崩溃场景验证 | 4、6、7 | 重启后留下的状态有明确处理结果 |

**推荐完成节奏：**准备 → 1 → 2A → 2B → 3 → 4A → 4B → 4C → 4D → 5A → 5B → 6A → 6B → 7A → 7B → 7C → 7D → 8。

第 3 步可以先设计和实现新接口，但应用入口的最终切换应与第 4 步一起完成。过渡期每个 Run 只能走一条执行与持久化路径，不能同时让旧 RunRecord 和新存储各自决定产品状态。

## 三、准备：固定行为基线

**做什么：**记录当前行为，确认后续变更的兼容范围，并让基础测试可重复运行。

**为什么：**迁移中出现失败时，要能区分原有问题、环境问题和新引入的问题。

**现有入口：**`app.server`、`run_agent_loop()`、`create_lead_agent()`、`ChatStore` 和当前 SSE HTTP 路由。

- [ ] 列出必须保留的行为：普通问答、工具调用、Goal 续跑、子 Agent 调用、断连后继续执行、历史消息查询。
- [ ] 记录当前 HTTP 路由和 SSE 事件字段；将需要改变的字段列为明确的协议变化。
- [ ] 将不启动 FastAPI 的完整 Run 流程列为迁移新增验收目标；准备确定性 Graph、真实临时存储与独立 Python 进程验证方式。
- [ ] 以现有测试确认 Loop、Stream、RunManager、包导入行为。
- [ ] 查明上一轮 `tests.test_run_persistence` 首个用例超时的原因，再将它作为迁移参考。超时不是通过，也不能直接断言是业务代码错误。
- [x] 明确历史数据库直接放弃；不读取、转换或删除旧数据。部署新版前手动删除旧数据库，使用当前 schema 新建。

**完成条件：**能说明当前哪些测试通过、哪些未验证；后续数据库操作有可重复的本地验证方式。第 1、2 步可以先推进，但数据库步骤不能以一个始终超时的测试环境作为验收依据。

上轮分析中的 57 个通过测试是当时的基线记录，不自动代表后续迁移后的结果。

## 四、第 1 步：让订阅有可靠的释放接口

### 2026-09-15 验收记录：已完成

已对照当前工作区实现与测试验收。`_Subscription.aclose()` 直接解绑队列，
无需先启动异步生成器；同步注册、事件顺序和缓存重放保持不变。
[Stream 生命周期测试](../tests/test_stream.py) 的 9 项测试全部通过，
覆盖下表全部场景，以及等待事件／处理事件期间取消、Stream 关闭唤醒。
[HTTP 消费方](../app/routes/run.py) 已在 `finally` 中关闭自己的订阅。

使用边界：提前 break 或处理事件期间取消时，消费方仍需在 `finally` 中
`await subscription.aclose()`；该接口不支持与同一订阅进行中的 `anext()` 并发关闭。
本次完成的是订阅释放，不代表后续产品 Run 生命周期迁移已经完成。

### 模块位置与目标

放在 `shikigen.stream`。Stream 管缓存与广播，订阅对象管理一个观察者自己的资源。

改动前 `subscribe()` 同步注册队列，清理却放在异步生成器的 finally 中。若从未迭代就关闭生成器，该 finally 不会执行。本步骤解决这个具体生命周期缺口。

### 接口与实现任务

借鉴 copy 的 `_Subscription`，让返回对象支持异步迭代和 `aclose()`。

- [x] 保留同步注册订阅的语义：调用 subscribe 后，接下来发布的事件必须能被该订阅收到。
- [x] 将“解绑队列”变成无需启动迭代也能执行的操作。
- [x] 让 `aclose()` 可重复调用。
- [x] 正常迭代结束、消费任务取消、手动关闭都释放同一个订阅。
- [x] Stream 关闭时唤醒已有观察者；关闭一个观察者不关闭整个 Stream。
- [x] 适配现有消费方，保持消息顺序和历史缓存重放行为。

暂时可以保持现有 StreamEvent 类型，不必同时把整个 Stream 改成泛型事件系统。

### 验收

| 场景 | 预期 |
| --- | --- |
| subscribe 后立即 aclose，从未 anext | 订阅被移除 |
| 同一订阅关闭两次 | 不报错，不影响其他订阅 |
| subscribe 后 publish，再开始迭代 | 收到该事件 |
| 两个观察者，一个退出 | 另一个继续接收 |
| Stream 关闭后订阅 | 收到已有缓存后正常结束 |

**交付物：**Stream 的资源释放调整、对应生命周期测试。验收通过后即可独立完成这一项。

参考：[当前 Stream](../packages/harness/shikigen/stream.py)、[copy Stream](../../shikigen-agent-copy/harness/stream.py)。

## 五、第 2 步：明确工厂的依赖和子 Agent 能力

### 2026-09-15 验收记录：2A、2B 已完成

- **2A：**工厂直接传递调用者的 saver，缺省和显式 `None` 均不创建默认存储。
  已检查工厂调用方；当前生产入口为 [HTTP lifespan](../app/server.py)，
  显式传入 `make_checkpointer(config)` 产出的 saver，当前配置使用 SQLite。
  测试中需要 JSON 的调用显式构造 `JsonCheckpointer`，验证对象身份及重开后恢复；
  不启用 checkpoint 时无需 thread_id 即可完成普通调用。
  SQLite 测试验证正常退出、调用者异常和 setup 失败时关闭连接，
  服务测试验证先 shutdown 执行资源、再退出存储上下文；包的目录外导入测试通过。
- **2B：**`task_tool_registry` 缺省／None 沿用主集合，显式空集合保持为空；
  `excluding()` 返回独立容器并保留工具顺序、实例身份，不修改父集合。
  实际委派测试覆盖两种 agent_type 和缺省、None、过滤、空集合四种参数模式。
  应用通过 `config.subagents` 的白名单／排除项决定策略，通用 task 仅另行禁止递归 task。
  当前 `config.json` 的 bash 类型仅有读工具；提示词会列出实际工具并说明受限能力，
  不把类型名视为执行权限。

**能力边界：**过滤后的容器仍共享工具实例和文件系统，不提供资源隔离，
子 Agent 也不会自动继承主 Agent 的审批 middleware。
当前 general 的 `tools: null` 配合 `disallowed_tools: [write_file, bash]`
只排除这两个名称；新增 MCP 工具若未被排除仍可进入 general，
不能据此认定其已接受审批或副作用限制。应用可用显式白名单进一步限定能力。

**本次验证：**以下命令共通过 81 项测试（包括第 1 步的 9 项），
另有执行资源／编排兼容测试 8 项通过；未调用真实模型或外部 MCP 服务。

```bash
.venv/bin/python -m unittest tests.test_stream tests.test_agent_factory tests.test_task_tool tests.test_tool_registry tests.test_package_imports tests.test_server tests.test_sqlite_checkpointer tests.test_json_checkpointer tests.test_app_config tests.test_loop tests.test_run_manager
.venv/bin/python -m unittest discover -s tests -p test_execution.py
```

首次将 `tests.test_execution` 加入模块式命令时，因该测试使用 `from test_loop import ...`
而发生导入错误；改用上述 discover 入口后 8 项通过。这是测试入口差异，未修改测试实现。
上述结果只作为本次第 1、2 步及相关兼容行为的验收依据，不替代准备阶段、
第 3 步完整验收或后续真实数据库迁移验证。

### 2A：Checkpointer 由调用者决定

**做什么：**让 `create_lead_agent(checkpointer=None)` 表示不启用持久化。

**为什么：**库工厂提供能力，应用入口选择存储；默认创建 JSON saver 会把两者绑在一起。

**接口：**`create_lead_agent(checkpointer=...)`；现有 `BaseCheckpointSaver` 参数继续沿用。

- [x] 找出工厂全部调用方，确认哪些依赖隐式 JSON 持久化。
- [x] 工厂直接使用传入的 saver，不隐式创建文件存储。
- [x] 需要 JSON 的调用者显式创建并传入；HTTP 服务继续显式传入 SQLite。
- [x] 保留现有 JSON saver 的可用性，避免把修改默认值扩大成删除实现。
- [x] 验证未启用 checkpoint 时普通 Agent 调用仍正常工作。

**验收：**None 不触发默认存储创建；传入 saver 的对象身份保持不变；服务器生命周期正确关闭它拥有的连接；包在项目目录之外仍能导入。

### 2B：主、子 Agent 分别接收工具集合

**做什么：**给工厂增加可选子工具集合，由应用组合能力。

**为什么：**子 Agent 不自动继承主 Agent 的 middleware，不能假设主 Agent 的审批策略自然覆盖子工具调用。

**接口：**`task_tool_registry`、`ToolRegistry.excluding(names)`、现有 `build_task_tool()`。

- [x] 子集合未指定时保持现有默认行为；显式空集合不能被误认为“未指定”。
- [x] `excluding()` 返回新的 registry 容器，不改动原容器。
- [x] task 工具构建子 Agent 时使用显式提供的集合。
- [x] 应用入口负责决定排除哪些工具，不在通用 task 实现中硬编码服务器策略。
- [x] 检查各 agent_type 的工具白名单和提示词，避免名字叫 bash 却没有执行工具。
- [x] 清楚区分“工具集合过滤”和“工具实例／文件系统隔离”。

**验收：**父集合不变；子 Agent 实际注册的工具等于预期集合；空集合和缺省参数行为不同；新增 MCP 工具不会被误认为自动接受了与内置工具相同的策略。

**交付物：**两项可独立验收的工厂改动。此时无需添加产品审批流程。

参考：[当前工厂](../packages/harness/shikigen/agent.py)、[copy 工厂](../../shikigen-agent-copy/harness/agent.py)、[copy 工具 registry](../../shikigen-agent-copy/tools/tool_registry.py)。

## 六、第 3 步：拆分产品 Run 与本地执行资源

### 2026-09-15 验收记录：第 3 步已完成，基础应用链路已切换

当前实现统一使用 `RunExecution`、`ExecutionRegistry`；参考项目中的对应名称为
`ActiveRunHandle`、`ActiveRunRegistry`。下文以当前实现命名为准，保留 `Stream.subscribe()`。
新链路只维护执行资源索引，通过 `execution.stream` 获取 Stream，
不再建立第二份 `StreamManager` 索引。执行注册与观察者订阅仍是两种独立职责。

- 已新增 [执行资源与结果](../packages/harness/shikigen/execution.py)：
  不包含产品 status；注册表校验归属、拒绝重复执行、按对象身份移除，shutdown 等待 Task 清理。
- 已新增 [execute_agent_loop](../packages/harness/shikigen/loop.py)：
  返回 completed/aborted/failed/interrupted 执行结果，不发布产品终态、不关闭 Stream；
  使用 checkpointer 时在 Graph 退出后读取状态，保留暂停的 checkpoint 坐标与中断信息。
  外部 Task 取消继续传播，不自动解释为用户取消。
- 已接通 [RunExecution 应用编排](../app/run_execution.py)：
  `start_run_execution()` 接收已持久创建的 Run 身份，创建并返回 `RunExecution`，
  通过 `ExecutionRegistry` 注册和回收；其 Task 包含执行及提交收尾；
  通过 `RunSettlement.settle_execution()` 获取已提交状态后发布终态。
  持久化失败发布 `stream_failed`，不冒充产品 error/completed。
  消费者仅释放订阅，执行结束自动回收，不依赖 HTTP 的 detach。
- 已新增 [资源与编排测试](../tests/test_execution.py)：
  用可控提交替身验证订阅隔离、提交前无终态、失败不发布成功、持久取消优先、
  shutdown 清理和旧执行不能误删新执行。这组测试使用存储替身。
- 已实现共享应用服务：[ThreadService](../app/services/thread.py) 提供 `create_thread()`
  和会话查询；[RunService](../app/services/run.py) 提供 `start_run()`、
  `wait_run(execution)`、`read_run(thread_id, run_id)` 及 Run 消息／事件查询。
  [Runtime](../app/runtime.py) 仅保存运行配置和依赖引用，不再包含业务或关闭方法；
  调用方使用 `runtime.threads.create_thread()`、`runtime.runs.start_run()` 等入口。
  `start_run()` 返回本次执行句柄；`wait_run()` 等 Task 与提交收尾后读取持久状态，
  存储异常直接传播，等待者取消通过 shield 与执行隔离。句柄在资源索引移除后仍可等待。
  只持有 ID 或重开进程的调用者使用 `read_run()`。订阅沿用 `execution.stream.subscribe()`。
  已接收的创建操作由 [ApplicationLifecycle](../app/lifecycle.py) 保留，
  调用者取消不会在“创建已提交、Task 未启动”之间留下孤儿。
- 已实现 [open_runtime](../app/composition.py)，统一打开产品存储、checkpointer 与 Agent；
  由 `assemble_runtime()` 组装配置、依赖与应用服务；退出时先调用
  `runtime.lifecycle.shutdown()` 回收创建与执行 Task，再关闭存储，
  初始化失败也释放已打开的依赖。
  [HTTP lifespan](../app/server.py) 和 [普通 Python 入口](../app/run.py) 使用同一上下文，
  路由调用共享运行接口，已删除路由内的 Task 创建及 `run_and_persist_status()`。
- 为完成切换，提前完成第 4 步所需的最小真实存储操作：
  `ChatStore.create_run()` 一次事务保存 running Run、生命周期事实及入口消息；
  `settle_execution()` 用条件更新提交状态与生命周期事实。已有终态不覆盖、不重复追加，
  interrupted 不填写 completed_at。单连接读取等待写事务结束，避免读到未提交状态。
  完整输出消息暂由原 middleware 保存，装配时设置 `persist_entry=False`，入口消息只有创建事务写入。

产品转换：新建 → running；running → completed/error/cancelled/interrupted。
completed/error/cancelled 为终态，interrupted 为非终态并继续阻止同 Thread 的新 Run。
完成与协作取消结算竞争时，以第一次有效提交为准。当前产品 schema 不保存公开的
pending 状态；interrupted → running、审批决策校验及同 Run resume 在第 7 步实现。

**验证：**[Runtime 与事务测试](../tests/test_runtime.py)、[HTTP 测试](../tests/test_server.py)
覆盖真实 SQLite 的创建／结算回滚、双连接排他、提交前读取隔离、等待取消、存储失败、
暂停持久化、关闭顺序及重开查询。[独立进程场景](../tests/runtime_no_http.py)
在导入前阻断 FastAPI、app.server 和 routes，使用确定性真实 Agent 与工具，
验证入口／AI／工具消息、已提交终态和重开后读取。没有调用真实模型或外部 MCP。

本次全量命令 `.venv/bin/python -m unittest discover -s tests -p 'test_*.py'`
共 **140 项通过**；本次涉及的代码通过 Ruff 检查与格式检查，`git diff --check` 通过，
独立入口 `--help` 可直接运行。数据库测试在沙箱外运行：当前沙箱内最小
`aiosqlite.connect(':memory:')` 也会卡住，同一复现在沙箱外正常连接并关闭；
因此未将沙箱内超时计为测试通过，也未据此判定业务逻辑错误。

**范围边界：**本次没有切换实际数据库；当前 schema 只支持新建数据库，旧库由部署者删除后
重建。排他目前由 `BEGIN IMMEDIATE` 事务内检查保证；数据库唯一索引、严格消息冲突校验与
统一事件写入器仍在第 4、5 步，不能把第 4 步整体标为完成。
存储接口已统一为原子 `create_run()` 与条件结算 `settle_execution()`，
已移除旧的分步创建、`start_run()`、`finish_run()` 及无条件状态更新入口，测试也使用新接口。
旧 harness 的 `run_agent_loop()`、`RunManager` 仍保留给独立 harness 测试，生产入口已无引用。
shutdown 的强制停止不伪造 cancelled，
留下的 running 状态由第 8 步启动恢复处理；当前不提供崩溃自动续跑。

最小独立入口：`.venv/bin/python -m app.run --config config.json '你好'`。
配置文件决定产品数据库与 checkpoint 路径，相对路径以启动目录为准；
可传 `--thread-id` 沿用 Thread。入口打印身份、等待收尾后打印持久结果与消息。
该命令使用配置中的真实模型与工具；离线验收使用上述确定性测试工厂。

### 先确定语义

**做什么：**产品 Run 保持用户任务身份；`RunExecution` 管理当前进程的一次执行资源。

**为什么：**同一个 Run 可以经历“执行 → 暂停 → 恢复执行”，但不能用一个 asyncio.Task 跨越进程退出或所有暂停阶段。

`RunExecution` 保存 run_id、thread_id、Task、取消信号和 Stream；持久 Run 保存状态、时间、错误码，以及以后加入的恢复坐标和累计用量。本地资源是否存在不直接等同于产品状态。

建议第一版接受新请求时直接把 Run 原子创建为 running，避免在没有调度队列时增加一个公开 pending 阶段。若未来保留 pending，需要说明由谁负责将它推进为 running。

### 接口与实现任务

接口进度：资源与结果采用 `RunExecution`、`ExecutionRegistry`、`ExecutionOutcome`，分别表示一次本地执行、执行资源注册表及执行结果。`Runtime` 仅为配置与依赖容器；业务接口位于 `ThreadService`、`RunService`，资源关闭位于 `ApplicationLifecycle`。入口与等待接口见上方验收记录。

- [x] 定义产品状态转换，明确 completed/error/cancelled 是终态，interrupted 是非终态。
- [x] 让执行资源清理与产品终态提交成为不同操作。
- [x] 让单次执行 Loop 报告完成、取消、异常或暂停结果，由独立 Run runtime 调用事务接口结算产品状态；执行层仍通过注入接口驱动消息与 checkpoint 保存。
- [x] 取消与正常完成同时发生时，明确以哪次有效持久状态转换为准。
- [x] 执行 Task 由应用保留，不由 HTTP 响应生成器拥有。
- [x] 本地注册表负责定位资源、等待结束与移除，不独立维护另一份权威产品状态。
- [x] 建立应用编排入口，让路由只调用编排，不直接拼接 Task、Stream、数据库收尾逻辑。
- [x] 共享运行入口覆盖创建 Thread、创建 Run、启动执行和查询；调用方不必预先手动拼接数据库操作，也不只暴露 `start_run_execution()` 骨架。
- [x] 定义 `wait_run()` 覆盖本次执行和持久化收尾；后续暂停时返回已提交 interrupted，存储失败显式报告，流 EOF 不作为 completed 的依据。
- [x] 事件订阅与执行所有权分开：未订阅或订阅者全部退出也正常执行、提交和清理；等待者停止等待不自动等于用户持久取消。
- [x] 将旧 `ServerRuntime` 拆为配置／依赖容器 `Runtime`、应用服务和 `ApplicationLifecycle`；各模块均不依赖 Request 或 app.state。
- [x] 保留原有 TaskGroup、取消竞争和 finally 的清理能力。

### 与第 4 步的切换方式

先完成新接口及其执行资源测试；随后在第 4 步接入事务化存储，一次切换应用调用链。迁移期间可以保留旧入口用于已有调用方，但同一个 Run 只使用一条链路。

不要把新版应用接到一个“只改类名、仍由内存 finish 决定数据库终态”的实现上，然后宣称状态拆分已经完成。

### 验收

- [x] HTTP 消费者退出后，Task 继续执行。
- [x] 本地 Task 结束并移除后，持久 Run 仍能查询。
- [x] shutdown 等待本地资源清理，不遗留后台 Task。
- [x] Loop 不导入应用数据库或 HTTP 对象。
- [x] 新运行模块可在阻断 FastAPI、app.server 和 routes 导入时直接构造和调用；已同时完成基础真实存储验收。
- [x] 同一 Run 的产品终态以 Run runtime 调用事务接口后的已提交结果为准。

**交付物：**资源接口、执行结果接口、应用编排骨架及资源生命周期测试；与第 4 步共同完成可运行的应用切换。

参考：[当前 RunManager](../packages/harness/shikigen/run_manager.py)、[当前 Loop](../packages/harness/shikigen/loop.py)、[copy 产品编排](../../shikigen-agent-copy/server/product_run.py)。

## 七、第 4 步：原子存储与提交后发布

2026-09-15：为接通第 3 步，已实现最小创建／结算事务及第 4D 的共享装配与独立运行。
随后 4A 已补齐新库 schema 约束、消息冲突检查与业务写入返回契约。历史库迁移已取消；统一发布接线随后在 4C 完成（见下方验收记录）。
下面仅勾选本次有实现和验证依据的子项。

### 4A：先定义数据和业务操作

### 2026-09-15 4A 验收记录：已完成（仅支持新库）

实现见 [ChatStore](../app/persistence/chat_store.py)、[状态与返回模型](../app/run_state.py)；
新增 [存储契约测试](../tests/test_storage_contracts.py)，并补充 HTTP 身份冲突映射测试。
创建返回 `RunWriteResult`，消息／事件业务写入返回 `EventWriteResult`，
结算返回携带完整 lifecycle 事件的 `CommittedRunState`；重试保留原事实身份、序号和时间。
旧 `MessageJournal.append_event()` 保留序号返回值，但不能绕过消息身份、内容和归属校验。
失败码默认 `execution_failed`，也可由结算调用方显式指定稳定 `error_code`。

新库使用部分唯一索引约束非终态排他，CHECK 约束状态值与完成时间，
当前只在新数据库上安装产品 schema；历史数据库不在支持范围内，不读取或改写其中内容；使用新版前需手动删除旧库并新建。

验证命令：`.venv/bin/python -m unittest discover -s tests -p 'test_*.py'`，
**153 项通过**；本次修改的 7 个 Python 文件通过 Ruff 检查与格式检查。
数据库测试在沙箱外使用临时数据库与确定性 Agent 执行，未调用真实模型或迁移实际数据库。
覆盖创建／消息／结算回滚、双连接消息重试、数据库直接写入排他、暂停事实重读与 HTTP 409。
该次 4A 验收仅覆盖返回契约；统一完整事件发布接线随后由 4C 完成。

**做什么：**让 Run 创建、终态转换与消息保存有明确的事务接口。

**为什么：**调用方不应自己掌握多次 INSERT/UPDATE 的顺序、回滚和状态竞争规则。

此处先定义最低限度的 Run、完整消息和 lifecycle 数据模型；第 5 步再补齐框架转换和传输契约，避免存储设计等待一个尚未存在的模型层。

具体字段、现有保证与目标接口见 [4A 数据与操作契约](4a-storage-contracts.md)。定义事务接口不改变保存时机的归属：完整输出消息在执行侧形成并经注入接口写入，入口消息由创建事务拥有，Run 生命周期由独立 Run runtime 编排；HTTP 不重新实现这些保存流程。

| 建议接口 | 必须一起完成的动作 |
| --- | --- |
| `create_run(entry_message=...)` | 创建 Run、记录 running、记录用户入口消息 |
| `append_message(...)` | 校验身份、内容和归属，保存或返回已有完整消息 |
| `complete_run(...)` | 校验旧状态、转 completed、记录 lifecycle |
| `fail_run(error_code=...)` | 校验旧状态、转 error、记录稳定错误事实 |
| `read_run(...)` | 返回持久状态及需要的元数据 |
| `list_run_events(...)` | 按确定顺序读取已提交完整事件 |

- [x] 一个 Thread 在数据库中最多有一个非终态 Run。
- [x] 用条件更新校验状态转换，不能只校验 run_id 是否存在（新结算接口）。
- [x] 相同消息身份、相同内容重复写入时返回原事实。
- [x] 相同消息身份、不同内容时显式报错。
- [x] 数据库唯一冲突转换成应用错误，再由 HTTP 映射为 409。
- [x] 事务遇到取消也回滚，避免只捕获普通 Exception 而遗漏取消路径（新创建／结算接口）。
- [x] 创建、结算及新的完整消息／事件业务接口返回已提交事件；`append_event()` 返回序号并委托统一校验写入路径。

### 4B：确定历史数据库处理边界

- [x] 明确不提供旧 schema 到当前 schema 的字段映射、升级入口或兼容读取。
- [x] 当前 schema 只在新数据库上安装；旧产品表不受支持。
- [x] 不对旧 Thread、Run、消息、checkpoint 或 WAL 副本做审计、转换、回滚或删除。
- [x] 明确启动前删除旧库并重新创建；应用启动不负责历史库检查或清理。
- [x] 新建数据库仍可与 checkpointer 使用同一路径；这一策略不改变当前存储归属。

### 2026-09-16 4B 验收记录：已完成（放弃历史库）

不再实现离线迁移入口、字段映射、审计副本、版本 marker 或回滚流程。验收只覆盖：新数据库
能创建当前表结构。真实部署由运维在停写后手动删除旧数据库并创建新库；本项目不替部署者
执行破坏性删除。

### 4C：连接执行结果与持久事实

建议顺序：Graph 执行结束 → 提交状态和完整事件 → 发布提交结果 → 关闭当前执行流 → 清理本地资源。

- [x] 完整消息和生命周期事件只有一个写入／发布入口，借鉴 `RunEventIngestor`。
- [x] 成功事务之后才推送持久事实（创建、完整消息和结算路径）。
- [x] 终态存储失败时不给观察者一个虚假的 completed；返回可识别的观察／执行错误并记录日志。
- [x] 区分“事务失败”和“事务成功但发布失败”，后者的事实可以通过后续读取恢复。
- [x] 入口消息既然已由创建事务保存，旧 Middleware 不再独立重复创建它。
- [x] 第 3 步的新执行结果接入这条链路，切换后移除已无调用者的重复收尾逻辑。

### 2026-09-16 4C 验收记录：已完成

**做什么：**接通创建事务、执行侧完整消息保存、执行结算与事实广播。
**为什么：**观察者接收数据库已经提交的事实，广播故障不会反过来改变业务结果。
**用什么 API：**应用层 [RunEventIngestor](../app/run_events.py) 实现 Middleware 的
`MessageJournal.append_event()`，委托 `ChatStore.append_committed_event()` 写入；
创建与结算继续使用 4A 事务，三条路径统一调用 `RunEventIngestor.publish()`。
`open_runtime()` 注入 ingestor 和共享执行注册表，harness 不导入应用存储。

- 创建返回的 running／入口消息事实在 Graph 开始前发布；入口 Middleware 不重复写入。
- 完整 AI／工具消息在执行侧形成后提交，再发布；token 和工具增量仍是临时执行事件。
- Graph 结束后提交结算、发布事实、关闭流、清理注册表。旧的分支收尾发布已合并；
  harness 的 `run_agent_loop` 仍有独立调用及测试，产品运行入口不使用它。
- 新增 `durable_event`，数据完整保留 `id/thread_id/run_id/seq/event_type/category/`
  `event_key/content/metadata/created_at`，可与 `list_run_events()` 查询结果直接核对。
  原 `status/error` 保留为已提交状态的现有投影；HTTP SSE 将完整事实投影为 event。
- 事务失败不发布候选事实。消息写入失败交由 Graph 错误结算；结算写入失败保持原异常，
  尽力通知 `run_persistence_failed`，不发布虚假完成；通知失败也不覆盖原异常。
- 提交后广播失败记录包含事实身份的日志，并尽力通知 `event_publication_failed`；
  Graph 和后续结算继续，`wait_run()` 返回持久状态。调用方通过 `list_run_events()` 补读。
  这不保证可靠投递，也未实现跨进程自动补发；流整体失效时只能依赖日志和后续查询。
- 幂等重放可再次广播同一事实，观察者按持久事件 `id` 或 `(thread_id, seq)` 去重；
  内存 Stream 的 `id` 与数据库事实序号是两个命名空间。内容冲突不发布。

验证覆盖真实 Graph 的 AI／工具消息、独立连接在发布时读取已提交行、完整事件逐项比对、
创建／消息／终态广播失败、消息写入失败、结算与通知同时失败、幂等重放及冲突、
interrupted 的完整 checkpoint 事实。测试使用临时数据库和确定性模型，不调用真实模型。

验收结果：全量 **172 项测试通过**（新增 6 项）；本次 Python 改动通过 Ruff lint／格式检查，
整个 `app/` 通过 ty 类型检查，`git diff --check` 通过。

### 4D：接通共享装配与无 HTTP 的运行入口

**做什么：**实现协议无关的 `open_runtime(config=...)` 异步上下文入口，接入第 4A—4C 的真实存储和编排；提供一个最小可执行 Python 入口，HTTP lifespan 和路由复用同一实现。

**为什么：**核心能直接执行 Graph，不代表完整 Run 已能独立运行。数据库连接、任务收尾和启动恢复也必须能脱离 FastAPI 使用。

**接口：**装配入口返回第 3 步定义的 `Runtime` 配置／依赖容器，通过其 `threads`、`runs` 服务提供 Thread 创建、Run 启动、等待和查询；事件订阅使用执行句柄。存储仍通过 checkpointer、MessageJournal／后续统一写入接口和运行存储接口注入，HTTP 负责把内部事件编码为 SSE。

- [x] 从 `app/server.py` lifespan 抽取配置、存储、checkpointer、Agent 和执行注册表的共享装配；HTTP 与独立入口不维护两份装配流程。
- [x] 共享上下文先回收执行和收尾 Task，再关闭它们使用的存储；初始化中途失败也释放已打开资源。
- [x] HTTP 的创建和读取路径调用共享运行接口，移除路由内重复的事务、Task 创建与终态收尾逻辑；保留请求校验、鉴权入口、错误映射与 SSE 编码。
- [x] 增加最小 Python 脚本或模块入口，说明可复制的启动命令、配置与存储路径，以及如何等待完成或消费事件；不要求同时开发交互式 CLI。
- [x] 独立入口的调用方维持事件循环与上下文直到所需执行及收尾结束；正常退出和执行异常都走共享清理流程。
- [x] 直接用运行接口暴露应用错误，例如 Thread busy、Run 不存在、存储失败；HTTP 状态码仅由路由映射。
- [x] 在阻断 `fastapi`、`app.server`、routes 导入的独立 Python 进程中测试，不借助 TestClient、ASGI lifespan 或监听端口。
- [x] 使用确定性 Graph 和真实临时存储验证普通问答、工具调用、入口消息和输出消息保存、已提交终态查询；不只用存储替身或直接调用 `agent.ainvoke()`。
- [x] 关闭并重新打开 runtime 后，仍能查询先前的 Thread、Run 和完整消息；不依赖旧内存注册表。
- [x] 验证无人订阅和订阅提前关闭时，Run 仍能完成持久化与资源清理；注入终态保存失败时，等待接口和订阅均不报告虚假成功。
- [x] HTTP 回归验证既有请求和 SSE 行为，并确认调用的是同一个运行模块。

第 4D 步完成基础独立执行；第 5 步继续完善消息归属，第 6 步补历史与 live 的统一观察，第 7 步补取消与审批恢复，第 8 步补共享启动扫描。这些能力不得另在 HTTP route 中重新编排。

### 验收

| 场景 | 预期 |
| --- | --- |
| 不启动 FastAPI，直接使用共享 runtime | 完成执行、持久化收尾与查询，重开存储仍可读取 |
| 创建过程任一步失败 | 不留下半个 Run 或孤立入口消息 |
| 两个请求竞争同一 Thread | 一个成功，另一个得到明确冲突 |
| 已进入终态后再次完成 | 不覆盖状态，不重复创建终态事实 |
| 消息重复与内容冲突 | 前者幂等，后者报错 |
| 数据库写终态失败 | 客户端收不到成功终态 |
| 写终态成功、发布前断连 | 读取持久结果仍能得到终态 |
| 事务内触发取消 | 没有部分提交 |

**完成条件：**第 3、4 步已共同接通 HTTP 与无 HTTP 入口的普通问答和工具调用，使用同一运行模块；独立进程真实存储验收通过；单一持久状态来源成立；旧数据库处理边界已明确为删除后重建。

参考：[当前 ChatStore](../app/persistence/chat_store.py)、[当前路由编排](../app/routes/run.py)、[copy RunPersistence](../../shikigen-agent-copy/server/persistence/run_persistence.py)。

## 八、第 5 步：消息身份、归属与契约

2026-09-17 已完成；2026-09-18 HTTP 改为 SSE。实现与验收细节见 [第 5 步记录](5-message-identity-and-event-contract.md)。
沿用放弃历史库、不增加 schema marker、暂不升级 event_version 的约定。

### 5A：完整消息身份和归属

**做什么：**集中转换完整消息，按 Thread 内持久事实确定唯一 Run 归属。

**为什么：**checkpoint 负责 Graph 状态恢复，持久事实负责产品历史；历史重放不能改归新 Run。
当前 Loop 通过 GraphEventAdapter 提取根图完整消息候选，存储判断归属，无需 checkpoint baseline。

**接口：**`message_content()`、`normalize_message()`、`EventStore.message_by_key()`，
以及现有 `MessageJournal`／`RunEventIngestor`。

- [x] 明确 message_id、tool_call_id、run_id 与 event_key 的含义和范围。
- [x] 使用 Thread 内持久事实作为归属依据；同身份仍校验完整内容和元数据。
- [x] 创建事务拥有入口消息；应用 middleware 不重复创建入口。
- [x] 同 Run 恢复重放返回已有事实；真实 interrupt/resume 测试通过。
- [x] 不同 Run 的历史重放保留原归属，不广播到新 Run。
- [x] 完整事实不可变，同身份内容变化明确报冲突。
- [x] 工具结果身份由 tool_call_id 决定，保留 artifact 省略与 null 的区别。
- [x] 根图 values 提供产品消息，子 Agent 内部消息不纳入父 Run。
- [x] 完整消息由 Loop → Ingestor 单一路径接入；Adapter 过滤重复快照，存储判断跨 Run 归属，不从 token 重建。

**关键验收：**确定性 Agent 在同 Thread 使用真实 SQLite checkpoint 连续执行两轮，
每轮仅保存本轮 4 条消息；实时身份对应持久历史。重复消息、工具重放、同 Run checkpoint
恢复和历史内容冲突均有测试。产品审批恢复 API 仍属于第 7 步。

### 5B：严格事件契约

**做什么：**用 Pydantic 判别联合定义完整消息、内部事件和当前 SSE 传输模型。

**为什么：**消费者需要区分实时预览、可恢复完整事实、产品终态和观察失败。

**接口：**`MESSAGE`、`EVENT`、`SSE_EVENT` 和 `RunSseEncoder`。

- [x] 内部事件不包含 SSE 帧格式，传输模型位于 app。
- [x] 严格校验消息／事件载荷；真实 Graph 预览带稳定消息／工具调用身份。
- [x] 观察失败与 Run error 分开，EOF 不表示 completed。
- [x] 明确未知事件／字段拒绝策略与 null／省略语义。
- [x] 采用 metadata／delta／event／error 四类 SSE；删除旧逐行协议、output_index 和版本切换。
- [x] 确定性场景覆盖普通回答、工具调用、重复事实、冲突与观察错误。
- [x] 暂无多语言消费者，不生成重复的 JSON Schema／客户端类型文件。

**完成条件：**身份、归属及契约验证通过。预览 seq 预留与重连投影留在第 6 步。

## 九、第 6 步：完整重建与实时跟随

### 6A：让预览与完整消息使用同一顺序身份

**做什么：**首次观察到消息增量时预留 seq，完整消息保存后复用它。

**为什么：**同一条消息不能在实时模式占一个位置，在历史模式又变成另一条。

**接口：**`reserve_message_sequence()`、`ingest_delta()`、`ingest_message()`。

- [x] Thread 序号分配在事务中完成，支持先预留后保存完整事实。
- [x] 同消息后续增量复用原 seq，不为每个 token 申请持久序号。
- [x] 完整消息覆盖同 seq 的预览；预览内容不同只产生诊断，不压过完整事实。
- [x] 未完成的消息可能留下序号空洞，消费者按大小排序但不要求连续。
- [x] 完整消息已经提交后再收到其增量，按明确协议错误处理。
- [x] 不把“预留到的最大 seq”当成全部历史均已提交的游标。

### 2026-09-18：6A 已完成

- `thread_sequences` 在写事务内统一分配 Thread 序号，生命周期和消息共用分配器；
  `message_sequences` 保存 AI 消息预留身份及原 Run 归属。没有旧库迁移或 schema marker。
- `RunEventIngestor.ingest_delta()` 首个增量预留，后续增量复用执行内缓存；
  `ingest_message()` 将根图完整消息提交到同一 seq。
- SSE delta 现在包含 `seq`、`message_id`、`field`、`value`。消费者按 seq 排序和覆盖，
  完整事实优先；文本预览与完整文本不同只记录诊断。
- Loop 顺序消费原始 Graph messages／根图 values，通过注入接口调用应用 Ingestor；
  已删除持久化 middleware、wait_preview 和 drained 协调。harness 不导入应用存储。
- 预留不是事实，不出现在历史查询中；较大 seq 先提交时，较小 seq 仍可能稍后提交。
  因此最大 seq 不能作为“此前全部提交”的续传游标。6B 完成记录见下文。
- 验证：170 项测试通过，覆盖真实两轮 checkpoint、多连接竞争、重新打开存储、
  预留跨 Run 冲突、序号空洞、乱序提交、提交后增量拒绝及预览纠正。

### 6B：增加只读的既有 Run 内容流

**做什么：**增加 `GET .../runs/{run_id}/stream`，完整重建当前 Run，必要时继续跟随实时输出。

**为什么：**观察已有任务与创建新任务必须是不同动作。

建议先实现全量重建，保留 SSE。每次连接先建立新投影，不能简单把整次重建追加到旧屏幕内容上。

- [x] 终态 Run 从数据库重建，不依赖 StreamManager 中还留有对象。
- [x] 活跃 Run 同步注册订阅，再异步读取历史，避免读取期间漏掉事件。
- [x] 以本次 invocation 的起点切分持久前缀与该 invocation 缓冲，不能拿“查询时最新历史”直接拼上“全部缓存”。
- [x] 处理读历史期间任务完成、Stream 关闭、`RunExecution` 从 `ExecutionRegistry` 中移除的竞争；连接持有的订阅仍能完成交付。
- [x] 仅关闭自己的订阅，不取消任务或移除其他观察者资源。
- [x] 暂时无法定位本地执行时返回明确的可重试错误，不创建新的 Graph 调用。
- [x] 明确拒绝尚未实现的 cursor 参数，避免消费者误以为支持增量续传。
- [x] 历史与 live 拼接由共享运行／观察接口完成；HTTP 只编码 SSE，独立调用方能消费相同内部事件。

### 验收

- [x] 模型调用计数在重连前后不增加。
- [x] 测试阻塞历史读取，在阻塞期间发布事件，解除后没有遗漏或重复。
- [x] 在历史读取期间完成任务，消费者仍得到完整结果和终态。
- [x] 两次完整重建的最终投影相同。
- [x] 大量文本增量最后只形成一条完整消息。
- [x] 两个观察者中一个断连，另一个不受影响。
- [x] 不启动 FastAPI，直接通过共享观察接口完成重建与跟随，模型调用计数不增加。

**完成条件：**刷新、断连重接、终态读取均不依赖重新执行任务。明确全量缓存仍有资源上限问题，在后续长时运行优化中处理。

参考：[copy 重连路由](../../shikigen-agent-copy/server/routes/runs.py)、[copy Ingestor](../../shikigen-agent-copy/server/product_run.py)、[缓存优化备忘](../../shikigen-agent-copy/docs/invocation-replay-cache-optimization.md)。

### 2026-09-21：6B 已完成

- 新增 `GET /api/threads/{thread_id}/runs/{run_id}/stream`，只读观察既有 Run。
  不调用 `start_run()` 或 Graph；Run 不存在或不属于指定 Thread 返回 404。
- 共享入口为 `await runtime.runs.observe_run(thread_id, run_id)`，返回
  [RunObservation](../app/run_observation.py)，可直接异步迭代内部事件；
  调用方在 `finally` 中 `await observation.aclose()`，即使尚未开始迭代也能释放订阅。
- 活跃执行先同步订阅，再异步读历史。`RunExecution.replay_start_seq` 在安装执行前
  固定为本次初始事实的首个 seq；此前事实取自数据库，本次事实与预览取自完整缓存和实时队列。
  该边界不是查询时的 MAX(seq)，也不是客户端续传游标。未来增加 resume 时，必须为新的
  invocation 设置对应边界，并保证缓存覆盖该边界起的事实；本步未实现 resume。
- 读取期间执行完成、Stream 关闭或注册表移除，不影响已经持有的订阅。
  已结束或 interrupted 的 Run 从数据库重建，无需内存执行对象。
  running 且无本地执行时复查持久状态，仍 running 则返回 503 和 `Retry-After: 1`。
- HTTP 仅编码 SSE；查询参数和 `Last-Event-ID` 返回 400。每次连接都应新建客户端投影，
  按 seq 合并，完整事实替换预览；不能把全量重建追加到旧投影。
- 读取失败／取消、观察者退出以及响应开始发送前断连都释放本连接的订阅，不取消执行。
- 验证包含历史读取阻塞期间的 100 个增量与最终提交、完成／移除竞争、持久前缀拼接、
  重复重建、四种结束／暂停状态重开数据库读取、双观察者隔离和 Graph 调用计数不增加；
  独立进程阻断 HTTP 导入后也验证同一观察入口。全量回归 **182 项通过**，Ruff 与格式检查通过。
  全量缓存和无界队列的资源限制仍待后续优化。

## 十、第 7 步：审批、取消、使用量与同 Run 恢复

这一阶段分四个任务完成，避免一次同时调试审批协议、取消竞争和用量统计。

### 7A：暂停成为可查询状态

**做什么：**接入审批 middleware，持久化完整 pending Interrupt 与准确恢复坐标。

**为什么：**消费者离开后，暂停请求仍应存在；恢复需要定位产生这次暂停的 checkpoint。

**接口：**`HumanInTheLoopMiddleware`、`CheckpointsTransformer`、`aget_state(..., subgraphs=True)`、`interrupt_run()`。这些接口来自 copy 已使用的方案，实施时以项目安装版本和确定性 Graph 验证具体事件形状。

- [ ] 先为少量明确工具配置 approve/reject，并校验策略引用的工具存在。
- [ ] 观察根 checkpoint，保存准确 namespace 和 checkpoint_id，不用“当前最新”替代暂停时坐标。
- [ ] 汇总父图与子图的全部待响应 Interrupt，保留稳定 ID。
- [ ] 同一事务保存 required 事实和 interrupted 状态。
- [ ] interrupted 占用 Thread 的非终态名额，但不要求保留运行中的 Task。
- [ ] 暂停后的 GET 重建能完整展示待审批内容。

**验收：**审批前工具未执行；刷新后 pending 内容相同；多个 Interrupt 全部可见；暂停不会错误发布 completed。

### 7B：接受响应并恢复同一个 Run

**做什么：**验证当前所有审批响应，持久化接受事实，再发起一次 resume。

**为什么：**“用户响应已接受”与“恢复调用已开始”存在故障间隔，必须能分别解释。

**接口：**`accept_approval_decisions()`、`resume_product_run()`、`Command(resume=...)`。

- [ ] 请求中的 Interrupt ID 集合必须与当前 pending 集合准确匹配。
- [ ] 验证每项 response 的数量、类型与允许动作；后续需要 edit/respond 时再扩展策略。
- [ ] 同一事务保存 resolved 事实和 running 转换，返回本次恢复所需坐标与输入。
- [ ] 事务成功后才启动 resume，保持原 run_id。
- [ ] 前一个暂停 invocation 的资源和用量收尾完成后，再向 `ExecutionRegistry` 安装新的 `RunExecution`。
- [ ] 重复响应或旧审批返回明确冲突，不悄悄创建第二次 resume。
- [ ] 审批冲突后，消费者通过读取现状收敛；不能推断“请求失败，所以服务器一定没接受”。

**验收：**并发响应只接受一次；同 Run 连续两次暂停均可恢复；第二次暂停不接受第一次的旧 ID；历史不重复归属；工具调用次数符合该确定性场景预期。

### 7C：让取消与审批、正常完成有一致规则

**做什么：**提供取消入口，先持久化 cancelled，再请求停止本地执行。

**为什么：**任务资源是否成功停止，不应让已经接受的取消被普通完成覆盖。

**接口：**`cancel_run()`、`RunExecution.request_cancel()`，以及与其他生命周期一致的已提交事件发布入口。

- [ ] 对 pending/running/interrupted 定义可取消规则，终态取消明确返回冲突或已有结果。
- [ ] 取消 interrupted 时，在同一事务写 invalidated 和 cancelled。
- [ ] 取消赢得状态竞争后，迟到的 complete 不得覆盖它。
- [ ] 让现有观察者也能获知持久取消结果。建议走统一发布流程，并保证终态不会被正在退出的执行流提前关闭而遗漏。
- [ ] 已没有活跃 `RunExecution` 的暂停 Run，仍能通过存储完成取消。
- [ ] 取消与恢复请求使用一致的 Thread 执行协调规则。

**验收：**取消先赢、审批先赢后取消、正常完成先赢三种场景各有确定结果；其他观察者能得到取消事实，或按明确协议重建后得到事实。

### 7D：明确用量累计与完成通知时序

**做什么：**每次 invocation 使用独立 tracker，将可获得用量累积到同一个 Run。

**为什么：**暂停前后属于同一用户任务，用量需要累加；同时不能把供应商尚未报告的数据当成准确计费事实。

**接口：**现有 `TokenTracker.summary()`、建议的 `accumulate_run_usage()` 或与执行结算合并的存储操作。

- [ ] 先检查本项目 callbacks 的传播，验证普通模型、Goal evaluator 和子 Agent 的统计范围，避免漏计或重复。
- [ ] 选择明确的时序：建议自然完成／暂停时先结算已知用量再发布完成／暂停通知；取消用量可能稍后收尾，查询语义需说明。
- [ ] 防止同一次正常收尾在多条 finally／错误路径中累计两遍。
- [ ] 如果结算允许自动重试，使用内部结算键做幂等；它无需成为新的公开 Invocation 实体。
- [ ] 用量存储失败不得悄悄被描述为统计完整，记录明确的可诊断状态或日志。
- [ ] 不将进程崩溃前尚未报告的用量补成伪造的零消耗。

**验收：**两次 invocation 用量相加；一次结算重复提交不重复累计（若支持重试）；完成通知与查询时序符合约定；取消保留已知用量。

- [ ] `resume_run()`、`cancel_run()` 等操作位于共享运行模块；HTTP 路由只转换请求和错误，不自行提交事务或启动恢复 Task。
- [ ] 不启动 FastAPI，直接调用同一运行接口完成暂停、读取审批、恢复同 Run、取消与用量查询；与 HTTP 入口具有一致的持久结果。

**阶段完成条件：**一个 Run 可以执行、暂停、刷新、审批、恢复、再次暂停并结束；取消竞争与统计语义都经过确定性场景验证；无 HTTP 入口具备同样的运行能力。

参考：[copy 审批策略](../../shikigen-agent-copy/server/config.py)、[copy 生命周期事务](../../shikigen-agent-copy/server/persistence/run_persistence.py)、[copy 产品流测试](../../shikigen-agent-copy/tests/test_product_run_sse.py)。

## 十一、第 8 步：启动恢复与崩溃验证

### 先限定恢复目标

**做什么：**恢复可查询、可继续审批交互的产品状态，识别丢失的执行。

**为什么：**进程重启后内存中的 `RunExecution` 消失，但数据库仍可能是 running 或 interrupted。

**接口：**`RunRecoveryCoordinator.reconcile_all()`、`reconcile_run()`、`list_nonterminal_runs()`、准确坐标的 checkpoint 查询。

第一版按单进程执行归属设计。running 没有本地 `RunExecution` 时收敛为 invocation_lost，不自动重放工具。未来自动续跑需要另行解决执行所有权、恢复意图和副作用幂等。

### 实现任务

- [ ] 恢复扫描放入共享 runtime 启动流程；HTTP 接收请求或独立入口允许发起 Run 前均完成扫描，不只在 FastAPI lifespan 内执行。
- [ ] 已有终态只读，不被扫描重写。
- [ ] 丢失本地执行的 pending/running 转为明确错误事实。
- [ ] interrupted 的准确 checkpoint 与持久审批匹配时继续保留。
- [ ] 审批事实与 checkpoint 永久不一致时记录 approval_state_corrupt。
- [ ] 存储暂时不可用时保留原状态，进入可观察的重试流程。
- [ ] 启动重试允许进程取消退出，不静默无限阻塞。
- [ ] 日志包含 thread_id/run_id、稳定原因码，公开响应不直接暴露内部堆栈。
- [ ] 读取／响应审批时执行必要的防御性校验，避免只在启动时查一次。
- [ ] 将“恢复失败”和“恢复后自动执行”区分清楚；本阶段不承诺后者。
- [ ] 崩溃矩阵以独立 Python 进程直接打开 runtime 验证；不启动 FastAPI，也能校验暂停事实并识别丢失执行。

### 崩溃验收矩阵

| 退出位置 | 重启后的预期 |
| --- | --- |
| 创建事务未提交 | 不存在半个 Run |
| Run 已提交但 Task 尚未启动 | 识别执行丢失，不重复创建入口消息 |
| 正常完成已提交、尚未发布 | 历史读取获得 completed |
| 审批事务尚未提交 | 仍是完整 pending 状态 |
| 审批已接受、resume 尚未启动 | 保留 resolved 事实，按执行丢失处理，不要求用户重新批准旧 Interrupt |
| resume 已开始后退出 | 不擅自再次运行可能已有副作用的工具 |
| interrupted 的 checkpoint 临时不可读 | 保留暂停事实，等待依赖恢复 |
| interrupted 的事实永久损坏 | 记录稳定错误，其他可恢复 Run 继续检查 |

进程崩溃测试使用临时存储和明确的同步点触发退出，不依赖固定 sleep 猜测时机。验证持久事实，而不只检查进程退出码。

**完成条件：**所有状态在重启后都有明确规则，故障矩阵经过验证；文档清楚写明单进程假设以及尚未支持的自动续跑。

参考：[copy 恢复协调器](../../shikigen-agent-copy/server/recovery.py)、[copy 启动编排](../../shikigen-agent-copy/server/composition.py)、[copy 崩溃测试](../../shikigen-agent-copy/tests/test_recovery.py)。

## 十二、每一项完成后如何 review

每次只围绕这次修改受影响的行为 review；涉及并发、事务和恢复时，优先验证失败路径及竞争结果。下面是建议的提交材料，不要求执行 Git commit：

1. 本次完成哪些勾选项、哪些仍未完成。
2. 新接口的调用方需要知道什么，复杂的顺序规则被收拢到了哪里。
3. 一条正常路径和一条关键失败／竞争路径的结果。
4. 实际运行的测试、失败和未验证范围。
5. 当前应用入口走哪条执行／持久化链路，是否仍有重复收尾或双写。

review 顺序沿用现有偏好：先看做得好的，再看需要修的，最后讨论替代设计。

## 十三、可以后续独立推进的工作

这些需求不构成上述迁移的前置条件，也不限制自行扩展：

- **显式 workspace_root：**当 harness 在多个工作目录运行时，由工具工厂接收路径，替代导入时 cwd 或源码目录常量。
- **内存与慢消费者限制：**为事件缓存、工具输出和订阅队列设置容量及超限行为；在真正长时间、高并发使用前完成。
- **增量游标重连：**必须先建立完整事件提交进度与缓存裁剪的正确关系，再提供 cursor。
- **多 worker：**加入执行 owner、租约和跨进程事件传递，不能继续用“本进程没有 `RunExecution`”判定执行丢失。
- **崩溃自动续跑：**定义可重放节点、工具副作用幂等与恢复意图，不能仅在启动扫描中再次调用 Graph。
- **后台子 Agent：**明确独立任务身份、取消、历史归属与恢复；当前 task 工具同步等待子 Agent 的语义不等于后台委派系统。

## 十四、总完成清单

- [ ] 准备完成：兼容范围、测试基线、数据库验证环境明确。
- [x] 第 1 步完成：所有订阅关闭路径正确释放资源。
- [x] 第 2 步完成：存储和主／子工具集合由调用者控制。
- [x] 第 3、4 步完成：产品状态与本地资源分离，完整事实先提交后发布；HTTP 与无 HTTP 入口共用运行模块及装配流程。
- [x] 第 4D 步完成：最小 Python 入口与启动说明齐备，阻断 FastAPI 导入的独立进程可完成执行、持久化、重开查询与资源回收。
- [x] 第 5 步完成：消息身份、归属与严格事件契约已实现。
- [ ] 第 6 步完成：重连只重建和观察，不重复执行任务。
- [ ] 第 7 步完成：审批、取消、重复恢复和用量有一致语义。
- [ ] 第 8 步完成：重启恢复规则与崩溃矩阵经过验证。
- [ ] 第 6—8 步新增的重建、取消、同 Run 审批恢复和启动恢复均可不经 HTTP 调用，没有重新引入路由编排。
- [ ] 现有功能回归通过，已失效的旧应用执行路径完成清理。
- [ ] 数据与协议切换说明完整，未验证项明确记录。

第 1—5 步已验收完成。下一步是第 6 步：完整重建与实时跟随；
实际数据库使用新版前需先删除旧库并从当前 schema 新建。

### 2026-09-18：完整消息采集入口调整

完整消息现在由 GraphEventAdapter 从根图 values 提取，Loop 与预览一起顺序接入 Ingestor。
第 4、5 步早期验收记录中的持久化 middleware 属于历史实现；当前代码已删除它。
同 Run 和跨 Run 的已有事实均不重复发布；完整消息身份与 seq 规则不变。
没有新增 checkpoint baseline、旧库兼容或 event_version 升级；6B 尚未实现。

本次完整消息入口迁移验证：171 项测试通过；覆盖真实逐字流式输出、根图消息提取、
Command 工具结果、多轮归属、同 Run 恢复去重及后续节点失败前的完整消息接入。
Ruff、格式检查与 diff 空白检查通过。
