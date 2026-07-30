# 多频道流式：astream_events 的三个频道

用户没有使用我建议的 `agent.astream(stream_mode="updates")`，而是自行发现了更高级的 `astream_events` API (v3)。这表明他能独立探索 API 表面。

`astream_events` 的三个并发频道：

| 频道 | 粒度 | 用途 |
|------|------|------|
| `messages` | token 级 | 逐字流式输出 LLM 文本 |
| `tool_calls` | 工具调用级 | 展示 tool_name、input、output_deltas、output |
| `values` | node 完���状态 | 同步完整 `messages` 历史，驱动下一轮输入 |

异步版用 `asyncio.gather` 并发消费三个频道，同步版用 `stream.interleave()` 串行交错。这个理解是准确的——`interleave()` 本质是同步版的 gather。

**Evidence**: `main.py` lines 70-92, `sync_agent.py` lines 61-78. 两个版本都能正确工作。

**Implications**: 用户已具备流式输出的完整心智模型。后续教 StreamBridge/pub-sub 时可以直接类比：StreamBridge 就是把这三个频道的事件从后台 task 投递到 SSE 消费者。
