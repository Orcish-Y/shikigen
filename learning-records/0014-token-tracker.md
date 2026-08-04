# Token 统计：LangChain BaseCallbackHandler

实现了 `TokenTracker(BaseCallbackHandler)`，挂在 `config["callbacks"]` 上，LangChain 每次 LLM 调用完成自动触发 `on_llm_end`。

**核心机制**：
- `on_llm_end(response: LLMResult)` — 从三条路径提取 token 用量（不同 provider 格式不同）：
  1. `generations[0][0].message.usage_metadata`（新版 LangChain）
  2. `llm_output["token_usage"]`（OpenAI 旧格式）
  3. `llm_output["usage"]`（某些 provider）
- 按模型分拆（`by_model` dict）
- `summary()` 返回可序列化 dict，通过 stream publish 给消费端

**集成**：
- `loop.py`：接收 `token_tracker` 参数，挂到 `config["callbacks"]`，完成后 publish "usage" 事件
- `main.py`：每轮创建新 tracker，`consume_agent_events` 处理 "usage" 事件

**数据流**：LLM 调用 → on_llm_end 累计 → run 完成 → stream.publish("usage") → main 打印

**Evidence**: `harness/callback_handler.py` (128 行), `harness/loop.py`, `main.py`
