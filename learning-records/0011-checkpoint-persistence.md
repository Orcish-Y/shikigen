# Checkpoint 持久化：LangGraph BaseCheckpointSaver 实现

用户实现了完整的 JSON 文件 checkpointer，继承 `langgraph.checkpoint.base.BaseCheckpointSaver`。

**核心实现**：
- `aput()` / `aput_writes()` — 序列化 checkpoint 和 pending writes 到 JSON 文件
- `aget_tuple()` — 通过 `alist(limit=1)` 获取最新 checkpoint
- `alist()` — 扫描目录、多维度过滤（thread_id、checkpoint_ns、checkpoint_id、before）
- `adelete_thread()` — 线程级批量删除
- `serde` 继承自 `BaseCheckpointSaver`，自动处理 LangChain message 序列化

**架构变更**：
- `agent.py`：`create_agent(checkpointer=JsonCheckpointer())` — 官方推荐方式
- `loop.py`：只传 `new_message`（新消息） + `config`（含 thread_id），不传全量历史。LangGraph 自动从 checkpoint 恢复、保存。
- `main.py`：删除 `messages: list[BaseMessage]` 手动管理。`thread_id` 固定为 "default"。
- 签名收敛：`record: RunRecord` 替代散列的 stream/run_id/abort_event 参数。

**文件格式**：`checkpoints_table-{encoded_thread_id}-{encoded_ns}-{checkpoint_id}.json`

**Evidence**: `harness/checkpoint/json_checkpointer.py` (274 行), `harness/loop.py` (85 行), `main.py` (106 行)

**Implications**: 阶段 3（Runtime 基础设施）完整了。StreamManager / Abort / RunManager / Checkpoint 四件套就绪。下一步进入阶段 4：扩展能力（web 工具、子 Agent、多轮 Goal 续跑）或优化（token 统计、摘要）。
