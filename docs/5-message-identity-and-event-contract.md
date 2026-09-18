# 第 5 步：消息身份、归属与事件契约

2026-09-17 实现记录。只支持当前数据库，不添加 schema marker、旧库检查或迁移。
2026-09-18 改为 SSE，删除 JSONL 编码与契约，不提供版本切换或旧协议兼容。

## 消息归属与写入路径

`messages.py` 集中转换 HumanMessage、AIMessage、ToolMessage，并用 Pydantic
判别联合校验产品完整消息。它不读 checkpoint、不保存执行状态、不写数据库。

| 身份 | 含义与范围 |
| --- | --- |
| `run_id` | 产品任务归属；一次暂停后的恢复仍使用原 Run |
| Human/AI `message_id` | 完整消息的稳定身份；不能为空 |
| `tool_call_id` | AI 发出的工具调用身份；同 Thread 内不得用于不同调用 |
| Tool `message_id` | 固定为 `tool-result:{tool_call_id}`，忽略框架临时 ID |
| `event_key` | `human:{id}`、`ai:{id}`、`tool:{tool_call_id}`；Thread 内按消息类型唯一 |
| `seq` | 持久事实在 Thread 内的顺序；本步不为预览预留 seq |
| 内存流 `id` | 仅表示当前内存流顺序，不作为 SSE id 输出；output_index 已删除 |

保留现有 middleware 正常写入路径：入口消息由创建 Run 的事务保存，应用装配设置
`persist_entry=False`；模型完成钩子提交当前完整 AIMessage，工具完成钩子提交最终工具结果。
不从 token 重建完整消息，不把整个 Graph values 快照当作新输出。

**本实现不需要调用前 checkpoint baseline。** Graph 自己恢复 checkpoint；数据库中的
Thread 消息记录负责持久归属。在 `BEGIN IMMEDIATE` 内按 Thread + event_key 查找已有事实：

- 同身份、同内容和元数据：返回原事实，保留原 run_id、seq 和时间。
- 同身份、不同内容或元数据：抛出 `MessageConflict`，不覆盖原事实。
- 旧 Run 的消息重放：返回旧事实，Ingestor 不向新 Run 广播。
- 同 Run 重放：可以再次广播同一事实；消费者按事实 id/seq 去重。
- 新 Run 重用旧入口消息 ID：创建事务失败，不留下半个 Run。

数据库另有 Thread 消息唯一索引，阻止绕过业务接口的重复归属。这里不扫描或校验
checkpoint 的所有历史内容；对实际提交的完整事实执行不可变校验。已有 snapshot 即使
多次出现也不会自行触发写入。未来若改为消费 root values，需要单独实现候选提取。

产品持久化仅安装在主 Agent 上。子 Agent 内部对话不写入父 Run；子 Agent 返回到父工具
调用的最终结果属于父 Run。文本预览忽略非 root namespace。尚未提供独立子 Run 历史。

工具 artifact 省略表示未提供；显式 `null` 表示明确提供空值，两者不同。artifact 必须为
JSON 值；不把任意 Python 对象转成字符串。content 支持字符串或包含字符串／JSON 对象的
block 数组，原样保留 block；本步不解释图片、音频或厂商专用 block 的展示语义。

## SSE 事件契约

`shikigen/event_contract.py` 定义协议无关内部事件；`app/run_contract.py` 定义
SSE 判别联合、内部事件投影和编码，不依赖 FastAPI。路由负责订阅与响应资源释放。
HTTP 只支持 `text/event-stream`，每帧为 `event: <name>\ndata: <JSON>\n\n`。
JSON 字符串中的换行会转义，不能拆成新的 SSE 帧。

参考 copy 的 `server/protocol/contract.py` 和 `server/protocol/sse.py`，最外层只有四类事件：

| SSE 事件 | 数据与含义 |
| --- | --- |
| `metadata` | thread_id、run_id、status；首帧提供归属，usage 通知也放在这里 |
| `delta` | message_id、field、value；当前 Loop 发布 content 文本增量 |
| `event` | seq、created_at、category、event_type、payload；完整已提交事实 |
| `error` | code、message、recoverable；观察失败，不修改持久 Run 状态 |

`event.category=message` 时，event_type 为 `created`，payload 是 human／ai／tool 完整消息；
`event.category=lifecycle` 时，event_type 为 `status_changed`，payload 含 Run status。
任务失败放在 lifecycle payload 中。内部 `durable_event` 在此投影为 `event`，
数据库字段和查询接口保持原样；HTTP 流不直接暴露数据库行。

删除原有 JSONL encoder、output_index、message.completed、tool_call.completed、
run.* 和独立 usage 传输事件，不保留协议版本开关。内部 status/error 仍是提交后的状态通知，
在 HTTP 上投影为 metadata；工具的完整结果通过持久 message 事实发送。

与 copy 的明确差异：本项目尚未实现第 6 步的预览 seq 预留，因此 delta 通过稳定 message_id
定位，而非 copy 的 seq path。reasoning 是契约允许的字段，当前 Loop 未接入 reasoning 流。
本项目已有 usage 流通知，放入 metadata 的可选 usage 字段；尚未实现持久用量累计。
审批事件将在第 7 步接入；本步没有添加 approval 的空实现。

完整消息是最终事实，覆盖同身份预览；重复完整事实按 seq 去重。EOF 只表示观察流结束。
不发送 SSE id；内存流 id 不是持久游标。未实现自动重连与 Last-Event-ID 恢复。
POST 创建入口使用 fetch 流消费；重发创建请求会新建 Run，不属于重连。

未知事件、未知结构字段、错误类型及非 JSON 值被拒绝；content block、工具输入、artifact
和 metadata 内部 JSON 字段允许扩展。省略字段不自动补成 null，artifact 显式 null 保留。
无法提供 message_id 的文本预览属于契约错误，不能用响应内索引代替稳定身份。
编码校验失败输出 `error(code=invalid_event, recoverable=true)` 并结束该订阅；
recoverable 表示可以查询已持久事实，不承诺自动续接。Run 执行不受影响。

## 验证边界

`tests/test_message_contract.py` 使用临时 SQLite 和确定性真实 Graph，验证：

- 同 Thread 连续两轮，checkpoint 保留 8 条消息，每个 Run 仅保存自己的 4 条。
- 实时回答和工具预览身份对应完整消息，所有输出通过严格 SSE 契约。
- 历史重复提交保留旧 Run，变更内容冲突，旧入口 ID 重用事务回滚。
- 工具框架 ID 变化仍幂等，artifact 省略与 null 冲突。
- 真实 interrupt/Command(resume=...) 重放同一节点，同 Run 事实不重复。
- 未知事件和结构字段被拒绝，观察错误与业务终态分开。

同 Run 恢复测试验证消息写入语义，不代表第 7 步的产品审批／resume_run API 已实现。

最终验证：`python -m unittest discover -s tests -p 'test_*.py'` 共 166 项通过；
本次修改的 Python 文件通过 Ruff lint／format，`git diff --check` 通过。
测试未调用线上模型。未运行独立静态类型检查器。

2026-09-18 SSE 验收：HTTP Content-Type、四类事件投影、中文与换行编码、显式 null、
usage、业务失败与观察失败区分、断连／取消释放订阅均通过。应用和测试已移除 JSONL 编码器与逐行 JSON 消费路径。
