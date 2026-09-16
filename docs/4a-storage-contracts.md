# 4A：ChatStore 数据字段与业务操作契约

日期：2026-09-15。4A 已实现并在临时数据库上验收；本页记录最终接口及后续阶段边界。4B 离线迁移工具已于 2026-09-16 完成副本验证，实际旧库尚未切换，见 [4B 说明](4b-storage-migration.md)。

对应任务：[迁移清单 4A](migration-checklist.md#4a先定义数据和业务操作)。设计背景：[业务事务](branch-comparison-and-migration.md#32-用业务操作封装事务完整事实先提交再发布)。

## 1. 位置与职责

**做什么：**定义需要保存的数据，以及创建 Run、保存完整消息、结算执行和读取历史的操作契约。

**为什么：**让调用方调用一次业务操作，就能获得一致的持久结果，无需自己安排多条 SQL 的顺序、提交、回滚和竞争处理。

**用什么 API：**以现有 `ChatStore.create_run()`、`settle_execution()`、`get_run()`、`list_run_events()` 为基础，提供完整消息操作与已提交事件返回模型。方法名称可以保留，不必为了对应清单拆出 `complete_run()`、`fail_run()`。

按此前的[持久化职责调查](agent-persistence-ownership-research.md)与[运行边界对照](agent-runtime-boundary-comparison.md)，需要区分保存对象、保存时机、读写实现和资源装配。

运行分为三层：HTTP / Python 入口 → 独立 Run runtime → 单次 Agent 执行。这里的 Run runtime 指运行服务与编排能力，不特指只保存配置和依赖的 `Runtime` 数据类。

| 职责 | 谁驱动／决定时机 | 接口与实现 |
| --- | --- | --- |
| 执行 checkpoint | Graph runtime 在执行边界驱动 | 注入 checkpointer，由 saver 实现读写 |
| 完整输出消息保存 | 执行 runtime / middleware 在消息形成处驱动 | 当前调用 `MessageJournal.append_event()`，具体后端由应用装配 |
| 产品 Run 创建、结算与恢复编排 | 独立 Run runtime，当前为 RunService 和执行编排模块 | 调用 `create_run()`、`settle_execution()` 等事务接口；恢复能力按后续阶段实现 |
| 数据约束、原子写入和查询 | 存储实现 | 当前 ChatStore 负责状态转换条件、归属、重复检查和 SQLite 事务 |
| 存储配置与连接生命周期 | 共享装配入口 | `open_runtime()` 打开、注入和关闭后端，HTTP 与 Python 入口复用 |

执行层可以通过注入接口主动保存消息和 checkpoint；“不导入应用存储”仅指不直接依赖 `app.persistence.ChatStore` 等具体产品实现。完整事实提交后再发布，逐 token 预览不因此成为已保存历史。当前入口消息归创建事务所有，执行侧识别该事实，避免重复创建。

当前 Run 编排与 ChatStore 放在 `app/` 是阶段性组织方式。可复用的 Run 调度、取消、恢复及 RunStore 接口可以纳入 harness/runtime；用户归属等产品语义由产品层承担。不能把 harness 永久限定为只执行一次 Graph，也不要求为分层立刻移动文件。

例如，“创建前检查 Thread 是否忙”应与创建写入放在同一个事务里。仅把检查移到 Service，再单独调用存储创建，会重新留下竞争窗口。

## 2. 当前数据字段

源码：[ChatStore](../app/persistence/chat_store.py)、[RunStatus](../app/run_state.py)。

### 2.1 Thread 与 Run

| 对象 | 当前字段 | 含义与约束 |
| --- | --- | --- |
| Thread | `id`、`user_id`、`title`、`created_at`、`updated_at` | 会话身份、所属用户和展示信息；迁移需保留 |
| Run | `id`、`thread_id` | 任务身份及会话归属；外键关联 Thread |
| Run | `status` | 当前产品状态；Python 有枚举，数据库有状态值 CHECK |
| Run | `error`、`error_code` | 诊断文本与稳定错误码；失败结算默认码为 `execution_failed`，调用方可显式指定 |
| Run | `created_at`、`updated_at`、`completed_at` | 创建、更新和终态时间；暂停时不设置完成时间 |

状态划分：

- 非终态：`pending`、`running`、`interrupted`。`pending` 仅为旧数据保留，新 Run 直接创建为 `running`。
- 终态：`completed`、`error`、`cancelled`。
- `interrupted` 表示本次执行暂停，仍占用 Thread，不能因此创建另一个 Run。

**已实现约束：**每个 Thread 最多一个非终态 Run。创建接口使用 `BEGIN IMMEDIATE` 加事务内查询，新库增加部分唯一索引 `uq_runs_one_nonterminal_per_thread`，直接 SQL 写入也不能绕过排他。状态值及终态／完成时间关系由 CHECK 约束保护。

产品 schema 版本单独记录在 `chat_schema`，不占用与 checkpointer 共库时的全库版本号。已有旧产品表但缺少版本标记、产品表不齐或版本不支持时，打开操作抛出 `SchemaMigrationRequired`；不自动迁移。完成显式副本升级前，旧库不能直接用于新版运行入口，但原数据保持可供旧实现或迁移工具读取。

### 2.2 已保存事件

目前完整消息和生命周期事实共用 `run_events` 表，不要求另建消息表。

| 字段 | 当前含义 | 已实现契约 |
| --- | --- | --- |
| `id` | 数据库事件行 ID | 与消息 ID 区分，保留原值 |
| `thread_id`、`run_id` | 事件归属 | 组合外键保证事件属于该 Thread 下的 Run |
| `seq` | Thread 内递增序号 | 历史按此排序；单个 Run 的序号无需连续 |
| `event_type`、`category` | 具体事件类型与大类 | 完整消息为 `message`，状态变化为 `lifecycle` |
| `event_key` | Run 内的去重键，可为空 | 完整消息必须有稳定身份；重复键比较类型、内容及元数据 |
| `content_json` | 事件内容 | 解码后按模型校验，不用字符串兜底掩盖非法数据 |
| `metadata_json` | 元数据，默认空对象 | 全部持久 metadata 参与重复比较 |
| `created_at` | 首次写入时刻 | 重复写入返回原时间，不能生成新的事实时间 |

当前唯一约束为 `(thread_id, seq)`，以及非空键的 `(thread_id, run_id, event_key)`。它没有保证同一消息跨 Run 的归属唯一；跨 Run 消息身份和 checkpoint 重放归属在第 5 步继续补齐。

### 2.3 最小完整消息与生命周期内容

当前消息内容由 [ChatPersistenceMiddleware](../packages/harness/shikigen/middleware/chat_persistence_middleware.py) 构造：

| 类型 | 当前内容字段 |
| --- | --- |
| 用户消息 | `type`、`content`、`message_id` |
| AI 消息 | 上述字段，加 `tool_calls` |
| 工具消息 | 基础字段，加 `tool_call_id`、`name`、`status` |
| 生命周期 | `status`；失败时可有 `message`；暂停时可有 `checkpoint`、`interrupts` |

目前消息 key 使用 `human:`、`ai:`、`tool:` 前缀加消息 ID；工具消息没有 ID 时回退到 `tool_call_id`。4A 校验承接这套输入：工具消息允许回退到调用 ID，AI 消息要求 `tool_calls` 列表，工具结果要求调用 ID 和 success/error 状态；内容必须是文本或 block 列表。更细的 block、工具参数及传输契约在第 5 步补齐。

完整消息必须保留工具调用和工具结果字段，不能只存文本。逐 token 增量不属于此处的完整持久事实。

## 3. 各操作的契约

### 3.1 创建 Run：`create_run(...)`

- **输入：**`thread_id`、`run_id`、带稳定 ID 的用户入口消息。当前输入类型是 `HumanMessage`。
- **检查：**入口身份有效、Thread 存在、该 Thread 没有非终态 Run。
- **原子写入：**Run 的 `running` 状态、running 生命周期事件、入口消息、Thread 更新时间。
- **重复调用：**当前不是创建幂等接口；重复请求不能默认返回原 Run。已有活跃 Run 会触发 `ThreadBusy`，其他身份唯一冲突转换为 `StorageConflict`。
- **返回：**`RunWriteResult(run, events)`，包含已提交 Run 及按 `seq` 排序的创建事件。提交完成后才返回。
- **错误：**保留 `ThreadNotFound`、`ThreadBusy`；身份唯一冲突抛出 `StorageConflict`。事务失败或取消时整体回滚。

不要把所有数据库唯一冲突都翻译成 `ThreadBusy`：Run ID 冲突和 Thread 已被占用是不同问题。HTTP 只负责把应用冲突映射为 409。

### 3.2 保存完整消息：`append_message(...)`

业务接口 `append_message(...)` 根据完整消息推导类型和稳定 key，调用 `append_committed_event(...)` 返回完整事实。原 `append_event(...)` 保留返回 `seq` 的 MessageJournal 兼容契约，内部委托同一校验与事务路径；它不是新的完整事实返回接口。

已实现契约：

- **输入：**Thread / Run 归属、稳定消息身份、消息类型、完整内容及约定元数据。
- **检查：**Run 归属存在，消息字段合法，身份非空，重复身份是否对应相同事实。
- **原子写入：**分配 Thread 内序号并保存完整消息；重试不增加记录。
- **相同身份、相同内容：**返回原已提交事件，保留原 ID、序号和时间。
- **相同身份、不同内容：**抛出明确的消息冲突应用错误，名称为 `MessageConflict`；禁止静默忽略或覆盖。
- **返回：**`EventWriteResult(event, inserted)`；`event` 与历史查询形状相同，`inserted` 区分新增与重放。
- **错误：**归属不存在使用 `RunNotFound`；非法消息与消息冲突区分；写入失败或取消时回滚。

比较使用严格序列化、排序对象键后的 JSON。JSON 对象键顺序不同不算冲突，数组顺序和消息内容变化算冲突。类型、完整 payload 和持久 metadata 纳入比较；生成的事件行 ID、序号和写入时间不参与比较。非法对象和 NaN 不会被默认转成字符串入库。

兼容 `append_event(...)` 同样校验消息类型、分类和稳定 key 的一致性。公开追加接口拒绝 lifecycle 和 `run_*` 事件，状态事实只能由创建／结算事务写入。

### 3.3 结算执行：`settle_execution(...)`

- **输入：**Thread / Run 身份、`ExecutionOutcome`。
- **当前转换：**完成 → `completed`，中止 → `cancelled`，失败 → `error`，暂停 → `interrupted`。
- **检查：**Run 存在，且更新语句限定旧状态为 `running`。
- **原子写入：**Run 状态、错误和时间、生命周期事件、Thread 更新时间。
- **重复／竞争：**已有终态或暂停时返回原状态，不覆盖，不再次写生命周期事实。返回值可能与本次传入 outcome 不同，发布方必须服从已提交结果。
- **返回：**`CommittedRunState(status, error, error_code, events, changed)`；重复结算返回原事件且 `changed=False`，不产生新生命周期事实。
- **错误：**不存在时 `RunNotFound`；失败时抛出错误，不能返回候选终态；事务失败或取消时回滚。

错误文本使用 `str(outcome.error)`，稳定码由 `error_code` 单独存储。默认失败码为 `execution_failed`；非失败 outcome 不能传入错误码。

`pending` 不能直接走正常结算，显式抛出 `InvalidRunState`；已终态或暂停但缺少匹配结算事件时同样报错。旧任务恢复在后续阶段处理。

当前生命周期 key 是 `running:{run_id}` 和 `settled:{run_id}`，只适合当前单次执行链。第 7 步实现同 Run 恢复前，必须调整生命周期事件身份，否则第二次结算会撞键；4A 不把它定义成永久的多次执行契约。

### 3.4 读取 Run 与历史

| API | 当前行为 | 使用契约 |
| --- | --- | --- |
| `ChatStore.get_run(run_id, thread_id)` | 返回字典或 `None` | 按组合身份查询；应用 `RunService.read_run()` 将不存在转为 `RunNotFound` |
| `list_messages_by_run(...)` | 按 `seq` 返回消息；不存在返回 `None` | 区分不存在与存在但无消息；Service 将不存在转为应用错误 |
| `list_run_events(...)` | 按 `seq` 返回全部事件；不存在抛 `RunNotFound` | 返回已提交事实，包括消息与 lifecycle |

当前同一连接的读取会等待写锁，避免暴露该连接尚未提交的状态。写入返回和历史读取共用 `CommittedEvent` 形状。

## 4. 返回模型与兼容边界

模型定义在 [app/run_state.py](../app/run_state.py)：

- `RunSnapshot`：身份、归属、状态、错误码／信息和时间字段。
- `CommittedEvent`：事件身份、归属、序号、类型、分类、key、内容、元数据和写入时间。
- `RunWriteResult`：创建后的 Run 快照及创建事件。
- `EventWriteResult`：完整事件及 `inserted` 标记。
- `CommittedRunState`：结算状态、错误、完整生命周期事件及 `changed` 标记。

这些返回值只在 commit 成功后交给调用方。写入返回与重开数据库读取的事实一致。

当前 middleware 仍通过兼容的 `append_event()` 获取序号，现有执行发布模块仍消费结算结果中的状态。4C 接入完整事件发布时使用新返回值，不再重新拼造事实；本次未宣称统一发布链路已经完成。提交后发布失败的补读能力在第 6 步继续完善。

## 5. 验收与后续工作

4A 已验证：

- 新库数据库级非终态排他、状态值与完成时间约束。
- 相同消息重试返回原事件；内容／元数据冲突报错且不增加记录；双连接并发重试只新增一条事实。
- 兼容 journal 无法绕过消息校验或自行写生命周期事实。
- 创建、消息写入、结算返回结果与另一连接读取一致；重复结算返回原状态、错误与暂停信息。
- 创建／消息／结算失败或取消回滚；原终态不被迟到结果覆盖。
- 身份冲突转换为应用错误，HTTP 映射为 409。
- 未迁移旧库被明确拒绝，schema 和数据未被改写。

新增场景见 [存储契约测试](../tests/test_storage_contracts.py)，既有回归见 [Runtime 测试](../tests/test_runtime.py)、[HTTP 测试](../tests/test_server.py) 与 [ChatStore 测试](../tests/test_chat_store.py)。完整验证结果记录在迁移清单的 4A 验收记录中。

4B 旧数据副本审计与迁移现已完成验证，实际切换另行安排。后续仍包括：4C 统一提交后发布、第 5 步跨 Run 消息归属与严格框架转换、第 7 步同 Run 恢复。这些步骤未因 4A 完成而自动完成。
