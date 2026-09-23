# Monorepo 重构：Harness/App 分层 + 独立进化

用户将平级模块结构重构为 deer-flow 式的 workspace monorepo。这是 6 周独立工作的成果（2026-08-12 → 09-23），远超任务要求。

**新结构**：
- `packages/harness/shikigen/` — 框架包（uv workspace + hatchling），import: `shikigen.*`
  - `core/` — agent, loop, execution, run_manager, stream, approval, graph_pause, context
  - `contracts/` — events, messages, runs, stream（跨层类型契约）
  - `middleware/` — goal, logging, tool_error_handling
  - `persistence/` — database, schema, chat_store, event_store, run_store, thread_store
  - `runtime/` — composition, lifecycle, recovery, run_execution, run_observation
  - `tools/` + `utils/`
- `app/` — FastAPI server（24 行）+ routes/run.py + routes/thread.py
- 边界铁律：app imports shikigen，shikigen 永不 import app

**用户独立完成的新能力**（未布置的任务）：
- Human-in-the-loop approval（`core/approval.py` + `graph_pause.py`，用 LangChain `HumanInTheLoopMiddleware`）
- `ExecutionRegistry` / `RunExecution` / `ExecutionOutcome` 强类型执行领域模型
- runtime recovery、run_observation
- contracts 层独立包
- 227 个 unittest 全绿（56 秒）

**Evidence**: `packages/harness/shikigen/`（40+ 文件）, `app/`（3 文件）, `tests/`（33 文件, 227 tests）, 边界 grep 通过

**Implications**: 学习目标已达成——用户已能独立设计、实现和演进 AI Agent Harness。MISSION.md 应更新：从 "转行学习" 到 "独立构建 agent 系统的工程师"。剩余方向：frontend/（Web UI）、cli/ 和 infrastructure/ 是空壳待填。
