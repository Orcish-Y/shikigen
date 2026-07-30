# StreamManager：事件流 pub/sub 解耦

用户实现了 `StreamManager` + `Stream`，将 agent 循环（生产者）和输出渲染（消费者）彻底解耦。

**核心设计**：
- `Stream` 基于 `asyncio.Queue`，`publish()` 写入事件，`subscribe()` 返回 `AsyncIterator`
- `close()` 通过 sentinel（`None`）唤醒消费者
- `StreamManager` 按 `run_id` 管理多个 Stream 实例

**泛型类型系统**：用户自发实现了 `StreamEvent[EventNameT, EventDataT]` 泛型 + `StreamEventVariant` discriminated union——TypeScript 的类型窄化思维迁移到 Python。`TypedDict` 定义每种事件载荷（`MetadataData`, `MessageData`, `ToolCallData` 等），`@overload` 让 `publish()` 有类型安全的调用签名。

**loop.py 和 main.py 的集成**：
- loop 不再通过回调输出，改为 `stream.publish("message"|"tool_call"|"error"|"status", data)`
- `try/except/finally` 生命周期：metadata → events → status/error → close
- main 用 `create_task(run_agent_loop(...))` 后台执行 + `async for event in stream.subscribe()` 消费
- 这是 deer-flow Gateway 的简化等价模式

**遇到的 bug**：`StreamManager.streams` 初版是类属性（所有实例共享），修正为 `__init__` 中的实例属性。

**Evidence**: `harness/stream.py` (149 行), `harness/loop.py` (64 行), `main.py` (78 行)

**Implications**: pub/sub 解耦就绪。下一步：abort 取消机制、RunManager（run 生命周期管理）。
