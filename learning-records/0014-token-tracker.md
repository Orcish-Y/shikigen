# Token 统计：LangChain BaseCallbackHandler 三路径 fallback

实现 `TokenTracker` —— 继承 `BaseCallbackHandler`，挂到 `config["callbacks"]` 上，LangChain 在 LLM 调用完成时自动触发 `on_llm_end`。

**三路径 token 提取**（不同 provider/LangChain 版本格式不同）：
1. `response.generations[0][0].message.usage_metadata.input_tokens` — 新版 LangChain
2. `response.llm_output["token_usage"].prompt_tokens` — 旧版 / OpenAI 格式
3. `response.llm_output["usage"]` — 某些 provider 直接放 llm_output

**架构集成**：
- `harness/token_tracker.py` — 独立模块（128 行）
- `loop.py` — 接受 optional token_tracker、挂到 config callbacks、完成后 publish "usage" 事件
- `main.py` — 每轮创建 tracker → 传入 loop → `consume_usage()` 打印统计

**数据流**：`on_llm_end → tracker 累计 → loop publish "usage" → main consume_usage → print`

**Evidence**: `harness/token_tracker.py`, `harness/loop.py`, `main.py`
