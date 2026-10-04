# 会话与运行查询契约

日期：2026-10-03。状态：用户已确认，接口待实施。所属票据：[确定会话 Run 发现与只读查询契约](001-run-discovery.md)。

这是已定稿的实施前数据契约，不表示接口已经实现。最终确认见[决议](001-run-discovery.resolution.md)，历史讨论见[讨论记录](001-run-discovery.discussion.md)；本文件统一记录该票据的完整契约。

## 1. 做什么、为什么、用什么 API

**做什么：**让首版聊天工作台可以列出带状态的会话、恢复最近运行的观察，并读取运行详情。

**为什么：**当前已有真实消息和 Run SSE，但会话列表没有运行状态或分页，历史消息没有运行状态，普通运行快照和事件查询尚未暴露为 HTTP。

**用什么 API：**

| API | 契约变化 | 用途 |
| --- | --- | --- |
| GET /api/threads | 增加游标分页及运行摘要 | 会话列表、第一页轮询 |
| GET /api/threads/{thread_id}/messages | 消息记录增加 run_status | 定位最近运行、读取历史 |
| GET /api/threads/{thread_id}/runs/{run_id} | 新增 JSON 查询 | 状态、错误、用量和时间 |
| GET /api/threads/{thread_id}/runs/{run_id}/events | 新增 JSON 查询 | 已提交事件和时间线 |
| GET /api/threads/{thread_id}/runs/{run_id}/stream | 沿用现有接口 | 全量重建，运行中实时跟随 |

首版的会话入口为 `/api/threads`，运行身份从会话条目或历史消息取得。独立历史 Run 列表及导航留到后续运行追踪能力；已出现于消息中的 Run 可通过其 ID 查询。

## 2. 会话与状态语义

- 面向用户使用“会话”“会话列表”；API 与代码继续使用 Thread 标识。
- 会话状态由当前或最近一次发起的 Run 派生。等待审批仍属于未终结运行，每个会话最多一个未终结 Run。
- 有未终结 Run 时，列表摘要指向它；否则指向最近一次发起的 Run。最近发起的任务与最近更新的任务是不同概念，不以旧 Run 的结算更新时间选择任务身份。
- 实施应保持列表中的最近 Run 与历史消息末条所属 Run 一致，沿用会话内任务串行、运行创建和首条用户消息原子提交的约束。

| run_status | 中文文案 | 普通发送 |
| --- | --- | --- |
| null，尚无 Run | 未开始 | 可用 |
| running | 运行中 | 禁用 |
| interrupted | 等待审批 | 禁用 |
| completed | 已完成 | 可用 |
| cancelled | 已取消 | 可用 |
| error | 运行失败 | 可用 |

`null` 仅表示该会话尚无运行；查询失败或未加载应显示对应读取状态，不能当成“未开始”。以上发送可用性仍受后端就绪和请求 pending 等条件约束。

## 3. GET /api/threads

### 请求与响应

提供必填正整数 `limit` 与可选 `cursor` 参数。前端首版传 `limit=20`，第一页不带 cursor；后端逐层传递 limit，store 不固定业务页长。2026-10-04 按用户追加要求调整，替代此前“仅 cursor、后端固定 20 条”的约定。缺少或非法 limit、重复参数及未知参数返回 422，并设置 no-store。

| 响应字段 | 类型 | 含义 |
| --- | --- | --- |
| data | 会话摘要数组 | 本页，最多 limit 条 |
| next_cursor | string 或 null | 加载更早会话的游标；null 表示此次查询边界下没有下一页 |

每条会话摘要保留既有 `id`、`user_id`、`title`、`created_at`、`updated_at` 字段，并增加：

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| run_id | string 或 null | 当前或最近发起运行的身份 |
| run_status | RunStatus 或 null | 同一运行在查询时已提交的状态 |

未创建过 Run 时，两字段同时为 null；存在 Run 时两字段都必须有值。列表无需返回用量、消息正文或审批参数。

### 排序与游标

- 服务端按 `updated_at DESC, id DESC` 排序，id 用于时间相同时的确定性排序。
- 客户端把 `next_cursor` 视为不透明字符串，原样带回，不自行构造或解析。
- 游标携带签发时末条会话的更新时间和 ID。查询下一页时使用该位置，不重新读取边界会话的当前时间来改变位置。
- 游标格式或内容无效时返回 422，不静默退回第一页。
- 空列表返回 200、data 为空、next_cursor 为 null。
- 每页除末页外返回 limit 条；原始 data 少于 limit 条或恰好 limit 条且没有后续记录时 next_cursor 为 null。游标不绑定页长，后续请求可以传不同的 limit。前端仍按原始短页或空游标结束自动分页，具体列表入口与反馈见[交互与验收阶段契约](006-interaction-acceptance.contract.md)。过滤或客户端去重后的数量不作为服务端分页边界。
- 更新时间可以变化，跨页查询不承诺固定快照。只轮询第一页也不保证发现任意多条同时发生的变化；显式重新加载会话列表时重新建立分页位置。

### 更新时间

沿用当前语义：创建会话、发起运行、审批后继续以及运行状态变更时更新会话的 `updated_at`；读取历史和详情不更新，流式 delta 不逐 token 更新。运行状态与影响排序的会话时间应在同一次事实提交中更新。

### 轮询与合并

- 窗口可见且后端就绪时，每 5 秒请求不带 cursor 的第一页。
- 隐藏到托盘、后端未就绪时暂停；窗口重新显示或后端恢复后立即刷新。
- 请求不重叠，失败保留已有列表。
- 按会话 ID 更新已有字段、插入新条目、去重，再按相同规则排序；不能直接忽略已有 ID。
- 第一页轮询不清空已加载的更早会话，不改变当前选中的会话或草稿。会话未出现在第一页，不表示它已被删除。
- 首次加载建立“加载更多”的 next_cursor，后续加载更多推进该游标；周期性第一页轮询不覆盖已建立的分页进度。显式重新加载列表才重置分页进度。
- 当前会话的实时状态由 SSE 提供；列表轮询与观察事实的合并优先级由[确定运行投影、观察连接与错误恢复](002-run-projection.md)继续确定。

## 4. GET /api/threads/{thread_id}/messages

保留当前响应结构：data 为完整历史消息数组，按 `seq ASC` 排序。保留既有消息记录字段和 content，并在每条记录外层增加 `run_status: RunStatus`。

- `run_id` 表示该消息所属运行，`run_status` 表示该运行在本次查询时已提交的状态。同一响应中，同一 Run 的消息应取得一致的状态。
- 运行状态从 Run 事实投影到查询结果，不存入消息正文，不当成消息创建时的历史状态。
- 所有返回消息统一携带 run_status，前端取末条消息的 run_id / run_status 即可定位最近运行；无需 latest_run 响应字段。
- 工具消息的 `content.status` 继续表示 success / error，与 run_status 分开。
- seq 属于会话顺序，允许空洞。不能因序号不连续判定丢失或失败。
- 新会话返回 200、data 为空；会话不存在返回 404。
- 此接口仍返回消息，不把审批请求或 lifecycle 伪装成聊天消息。它们由 Run stream 或 events 查询提供。

## 5. GET /api/threads/{thread_id}/runs/{run_id}

返回 `{data: RunSnapshot}`，沿用已有 RunSnapshot 身份和字段。

| 字段 | 类型／含义 |
| --- | --- |
| id | Run 身份；与路径 run_id 相同 |
| thread_id | 所属会话 |
| status | running / interrupted / completed / cancelled / error |
| error、error_code | 可空错误信息 |
| created_at、updated_at | UTC ISO 8601 时间 |
| completed_at | 终态时间；running / interrupted 时为 null |
| usage | Usage 或 null；null 表示未知，不显示为零 |
| usage_pending | boolean，当前用量是否仍待结算 |

Usage 沿用 `total_input`、`total_output`、`total_tokens`、`calls`、`by_model`；by_model 内为各模型的 input / output / calls。

RunSnapshot 使用 id，SSE metadata 使用 run_id，客户端应在边界转换为同一运行身份，不要求后端修改已有 cancel 或 SSE 契约。

## 6. GET /api/threads/{thread_id}/runs/{run_id}/events

返回 `{data: RunEvent[]}`，取得查询时已提交的全部事件，按 `seq ASC` 排序。首版不增加事件分页或过滤参数。

RunEvent 采用现有 SSE `event` 的 data 形状：

| 字段 | 含义 |
| --- | --- |
| seq | 会话内持久序号，允许空洞 |
| created_at | UTC ISO 8601 时间 |
| category | message / lifecycle / approval |
| event_type | 与现有 SSE 一致，见下表 |
| payload | 与该类别匹配的完整载荷 |

| category | event_type | payload |
| --- | --- | --- |
| message | created | 完整用户、Agent 或工具消息 |
| lifecycle | status_changed | status 及可选 message / error_code |
| approval | required / resolved / invalidated | 对应审批载荷，保留 checkpoint 与 Interrupt 身份 |

从已提交事件投影到公开 RunEvent 的规则应与现有 SSE 共用；不把数据库的 event_type / content 格式直接作为第二套前端事件协议。此接口不返回未提交 delta，也不持续推送新事件。

## 7. 恢复当前会话

1. 读取会话历史；没有消息时进入尚无运行的视图。
2. 取得末条消息的 run_id 和 run_status。
3. running / interrupted：调用已有 GET Run stream，全量重建当前观察。
4. completed / cancelled / error：可先显示消息与终态，读取用量、错误和时间时调用 Run 快照，需要事件时调用 events 查询。
5. 历史查询到建立观察之间可能有状态变化，以之后取得的当前事实收敛显示。

等待审批的 GET stream 首先返回当前 metadata，再回放消息、生命周期和审批事件；后端校验待审批事实与 checkpoint，前端恢复当前仍有效的审批。回放结束后 Run 仍可为 interrupted。

GET stream 沿用现有无游标契约：不接受查询参数及 Last-Event-ID。重连为全量重建，不自动重发 POST；消息按 seq 合并，历史生命周期不能覆盖 metadata 中较新的当前状态。审批提交调用原 approval-decisions 接口，继续同一个 Run。

## 8. 查询与恢复的边界

四个 JSON GET 查询只读取已提交事实：不启动执行、不接受审批、不取消任务，不触发 Graph 恢复校验或写入错误事实。HTTP 适配经 Runtime 的纯读查询入口访问持久数据，并验证会话和运行归属。

现有 `RunService.read_run()` 在 interrupted 时调用恢复校验，发现损坏可能持久化 error；新增 JSON 快照不能未经区分就直接复用该行为。应提供或拆分纯读入口，GET stream 继续沿用现有恢复校验。

快照和事件是各自查询时的事实，两个独立请求不承诺事务上的同一时刻。JSON 查询响应采用 `Cache-Control: no-store`，避免缓存旧状态；客户端仍需处理请求间状态变化。

| 情况 | HTTP／处理 |
| --- | --- |
| 会话不存在 | messages 返回 404 |
| Run 不存在或不属于指定会话 | snapshot / events 返回 404 |
| 游标无效 | threads 返回 422 |
| 持久数据暂不可读 | JSON 查询返回 503 和 Retry-After: 1；保留已显示数据 |
| 存储事实损坏或其他服务端错误 | 返回 500；查询不自动把 Run 改成 error |

GET stream 的恢复校验、503、观察 error 等既有语义继续沿用。前端错误展示、重试节奏、状态来源竞争和请求失效处理由运行投影票据细化。

## 9. 实施衔接

- 后端查询层负责归属校验、分页位置、已提交状态读取和公开事件投影；HTTP 层负责请求参数、状态码与响应封装。
- 前端 BackendSession 增加分页、快照和事件读取方法，适配原会话列表从裸数组到分页响应的变化。
- 运行投影、审批交互和详情样式继续通过地图的后续票据确定；新增状态文案和控件遵守[当前设计规范](../../../../frontend/design.md)。
- 不以票据关闭推断应用已实现或通过测试。

## 10. 依据

- [PRD](../../../frontend/frontend-prd.md)
- [差距审计](../../../frontend/frontend-gap-audit.md)
- [会话路由](../../../../app/routes/thread.py)
- [Run 路由](../../../../app/routes/run.py)
- [SSE 公开事件契约](../../../../app/run_contract.py)
- [运行状态与快照](../../../../packages/harness/shikigen/contracts/runs.py)
- [运行服务](../../../../packages/harness/shikigen/runtime/runs.py)
- [观察重建](../../../../packages/harness/shikigen/runtime/run_observation.py)
- [暂停恢复校验](../../../../packages/harness/shikigen/runtime/recovery.py)
