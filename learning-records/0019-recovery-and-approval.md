# Run Recovery + Approval 续跑：独立完成的生产级功能

用户在 monorepo 重构后独立完成了两个未布置的生产级功能（2026-09 期间，git 历史可查）：

**Run Recovery**（`runtime/recovery.py` + `tests/recovery_process.py`）：
- 进程崩溃后孤儿 run 的恢复机制——deer-flow 的 `ORPHAN_RECOVERY` 对应概念
- 恢复进程（recovery_process）作为独立测试 fixture

**Approval 续跑**（`core/approval.py` + `core/graph_pause.py` + `tests/test_approval_resume.py`）：
- Human-in-the-loop：危险操作前暂停 graph，等待人工批准
- 基于 LangChain `HumanInTheLoopMiddleware`
- pause → resume 的完整生命周期，含 checkpoint 续跑

**相关 commit 序列**：
- feat: add approval resume, run cancellation and usage tracking
- feat: add read-only run observation and SSE replay
- refactor: move runtime and persistence into harness package
- refactor: split harness contracts and core modules

**Evidence**: git log, 227 tests 全绿（67 秒），工作区干净

**Implications**: 用户已完全脱离任务驱动——自己在发现需求、设计、实现、测试。教学角色已从 "布置任务" 转为 "review + 顾问"。下一步：frontend/（Web UI）。
