# RunManager：Run 生命周期管理

用户实现了 RunManager，将散落在 main.py 的 run 管理逻辑收敛到一个类中。

**核心结构**：
- `RunRecord` — 纯数据 dataclass：run_id、thread_id、stream、status、task、abort_event、created_at
- `RunManager` — 生命周期操作：create、get、cancel、set_status、remove、get_active_by_thread、active_count

**关键设计决策**：
- `create()` 内部自动创建 Stream（通过持有的 StreamManager）
- 同 thread 互斥：`get_active_by_thread` 检查 PENDING/RUNNING 状态，重复 create 抛异常
- `cancel()` 设置 `abort_event`，由 agent loop 协作式停止，不直接取消后台 task
- `remove()` 同时清理 `_runs` dict 和 `stream_manager`
- main.py 提取了 `consume_agent_events()` 函数，将流消费和 agent_task 等待分离

**遇见的问题**：`await agent_task` 初版缩进错误在 for 循环内，导致第一个事件后即阻塞。

**Evidence**: `harness/run_manager.py` (83 行), `main.py` lines 38-58

**Implications**: Runtime 基础设施的最后一块是 Checkpoint 持久化——RunManager 已就绪，下一步将 run 状态+消息历史持久化到磁盘/数据库。
