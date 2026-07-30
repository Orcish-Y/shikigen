# Abort 取消机制：asyncio.wait + FIRST_COMPLETED race

用户实现了 `abort_event` 取消机制，遇到了 `asyncio.gather` 并发模式下的一个经典问题：多个协程各自在 `async for` 中迭代，单个 handler 的 `break` 无法影响其他。

**解决方案**：不检查 handler 内部，而是在外部 race：
- `asyncio.wait({gather, abort_wait}, return_when=FIRST_COMPLETED)`
- abort 赢了 → 取消 gather task → publish "cancelled"
- gather 赢了 → 正常完成 → publish "completed"

**关键 API 理解**：
- `asyncio.Event` ≈ 前端的 `AbortController`——跨协程信号传递
- `.set()` 设 flag + 唤醒所有 `.wait()` 的等待者
- `.is_set()` 非阻塞检查（适合循环内轮询）
- `asyncio.wait(return_when=FIRST_COMPLETED)` 实现 "race" 语义

**当前状态**：loop 层实现了 abort 检测，但 main.py 还没有触发入口（无键盘快捷键/超时调用 `.set()`）。下一步。

**Evidence**: `harness/loop.py` lines 53-88
