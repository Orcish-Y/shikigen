# Agent 工厂 + 执行循环抽象

用户完成第二阶段，实现了完整的核心 harness：

- `create_lead_agent()` — Agent 工厂，封装 model + tools + middleware + system_prompt → create_agent()
- `run_agent_loop()` — 执行循环，封装 astream_events 的三频道消费 + 动态 gather + messages 原地更新

关键设计决策：
- 回调签名选择：`on_message(text: str)` 而非 `on_message(stream)`——隐藏 astream_events 内部细节
- 动态 task 构建：`get_event(stream)` 根据传入的回调动态组装 gather 列表
- `messages[:]` 原地更新保留在 loop 内部——调用者不用关心状态同步

**Evidence**: `harness/agent.py`, `harness/loop.py`, `main.py` (64 行)

**Implications**: 核心 harness 就绪。下一阶段进入 Runtime 基础设施（StreamManager、RunManager、checkpoint 持久化），或者扩展能力（web 工具、子 agent、取消机制）。
