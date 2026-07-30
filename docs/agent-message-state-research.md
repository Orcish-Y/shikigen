# Agent 消息状态与流式事件调研

## 结论

针对 `main.py` 目前订阅的 `kind == "values"`，二选一应选**方案 2：用
`item.messages` 替换本地 `messages`**，而不是把它追加进去。`values` 是每一个
graph step 之后的**完整状态快照**；一次含工具调用的 agent run 会产生多个快照，每个
都含此前的历史。把每个快照的 `messages` 追加到本地历史会重复用户消息、AI 消息与
工具消息，并在下一轮把这些重复内容再次发给模型。

更符合 LangChain/LangGraph 主流用法的方案是订阅 `updates`：只把 model 节点提交到
agent state 的新 `AIMessage` 合并/追加到本地历史；`messages` 流则仅用于逐 token
显示，不应用作持久历史。若业务只要「最终给用户的回复」，应从 state 更新中筛选最终的
文本 `AIMessage`（通常排除仍带 `tool_calls` 的中间 AIMessage），并仍保留工具消息在
模型上下文里，以保证下一轮工具调用序列有效。

## 官方语义与建议

- LangGraph 的 [`values` 流模式](https://docs.langchain.com/oss/python/langgraph/streaming)
  在每个 step 后输出完整 state；`updates` 只输出该 node 的 state update；`messages`
  输出 `(message_chunk, metadata)` 的 token/chunk 流。因此 `values` 适合「替换状态
  镜像」，不适合「增量追加消息」。
- LangChain 的 [agent streaming 文档](https://docs.langchain.com/oss/python/langchain/streaming)
  对 `create_agent` 说明：模型消息已被 agent state 跟踪时，使用
  `stream_mode=["messages", "updates"]`；从 `updates` 的 `update["messages"][-1]`
  取得已完成消息。只有完成消息没有写入 state 时，才需要自行累积 chunks。
- LangGraph 的 [Graph API 状态文档](https://docs.langchain.com/oss/python/langgraph/graph-api)
  建议消息 channel 使用 `add_messages` reducer：新 message ID 追加、同 ID 更新/替换。
  没有 reducer 的 state 更新会替换整个 `messages` 列表。

## 对当前程序的直接建议

当前 [main.py](../main.py) 在发起 run 前已经手动追加用户消息。保留 `values` 时，
在一轮流结束后的最后一个 `values` 快照执行下面的语义即可（属性/字典访问以运行时
`item` 类型为准）：

```python
messages = list(item["messages"])  # 或 list(item.messages)
```

在当前 `main()` 中，`messages` 是模块级变量，实际应使用
`messages[:] = item["messages"]`（或先声明 `global messages`），避免函数内赋值创建局部变量。
不要写成 `messages.extend(item.messages)`。这样会让本地 `messages` 始终是当前 agent
state 的镜像；需要注意：若将来配置了摘要/裁剪 middleware，state 可能是「摘要 + 最近
消息」，而不再是审计意义上的完整聊天记录。完整可展示历史应另做 append-only 事件存储。

如果改成 `updates`，应只处理 model 节点写入的 `update["messages"]`，按消息 ID 去重/替换；
不要用 token `messages` 流构建历史。

## DeerFlow 的做法

DeerFlow 将「运行中的 graph state」与「可回放的完整聊天历史」分开：

1. Runtime 用 `graph.astream(..., stream_mode=...)`，并明确约定 `values` 为完整状态、
   `updates` 为 `{node: writes}`、`messages` 为 `(chunk, metadata)`。见
   [`worker.py:1-13`](../../deer-flow/backend/packages/harness/deerflow/runtime/runs/worker.py)
   与其多模式流处理
   [`worker.py:735-779`](../../deer-flow/backend/packages/harness/deerflow/runtime/runs/worker.py)。
2. 公共 `messages-tuple` 模式会映射到 LangGraph `messages`，并保留独立的 `values`、
   `updates` 模式，而不是把三者混用。见
   [`stream_modes.py:7-46`](../../deer-flow/backend/packages/harness/deerflow/runtime/stream_modes.py)。
3. Thread state 的 messages reducer 以 message ID 合并：已有 ID 替换、没有 ID 追加，
   还能处理删除。这是 `add_messages` 语义的实现。见
   [`thread_state.py:268-362`](../../deer-flow/backend/packages/harness/deerflow/agents/thread_state.py)。
4. 为防止摘要/裁剪后的 checkpoint state 丢失早期对话，DeerFlow 还在 LLM 完成时将每条
   完整 `AIMessage.model_dump()` 写入 append-only 的 RunEventStore。见
   [`journal.py:381-445`](../../deer-flow/backend/packages/harness/deerflow/runtime/journal.py)。
   这说明「state 快照」服务于下一次模型调用，而「消息日志」服务于完整历史/界面回放；
   两者不应互相替代。

### 适用于此项目的选择

| 目标 | 合适做法 |
| --- | --- |
| 继续只监听 `values` | 每个快照替换 `messages`，最终状态作为下一轮输入。 |
| 实时显示回复 | 继续用现有 `messages` token 流。 |
| 可靠维护会话 state | 改订阅 `updates`，按 ID 合并已完成 message。 |
| 永久保存完整聊天记录 | 另建 append-only 日志，每条完成的 Human/AI/Tool message 写一次；不要把 `values` 快照当日志。 |
