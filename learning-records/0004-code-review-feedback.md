# Code Review 反馈：双重 System Prompt 与调试残留

Review 指出的两个问题：

1. **双重 system prompt**：`create_agent(system_prompt="...")` 已自动注入 SystemMessage 到消息列表最前。用户又在 `messages` 里手动加了 `SystemMessage(...)`。多数 provider 拒绝两条 system 消息。解决：二选一。

2. **调试残留**：`tools/add.py` 的 `return a + b - 100` 有一个 `- 100`，显然是测试/调试用的。

**Evidence**: `main.py` lines 18-20 vs lines 24-26 (双重 prompt)。`tools/add.py` line 7 (`- 100`)。

**Implications**: 对 `create_agent` 的 system_prompt 参数理解需要精确化——它不只是"传给 LLM"，而是"自动注入到消息列表"。这类 framework 隐式行为是前端开发者最需要适应的概念——类似 React 的 automatic batching 或 Vue 的 reactivity proxy。
