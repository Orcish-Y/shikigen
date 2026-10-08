# Tauri 桌面前端：版本化事实合并 + 全量 wire 校验

用户独立完成了完整的前端（2026-09-24 → 10-08），项目迁移至 Windows 宿主机（Tauri 需要）。

**技术栈**：Tauri 2 + React 19 + Vite 7 + TS + Tailwind 4 + pnpm，react-markdown + rehype-sanitize。

**核心架构**（40+ 源文件，28 测试文件）：
- `run-protocol.ts` — 全量 wire 校验：每个 message/run/event/approval 载荷经 type guard 验证后才进状态；`RunProtocolError` 保留原始 payload
- `run-projection.ts` — 版本化事实合并模型（`RunFieldVersion` 按字段组计数），解决 POST stream vs GET observation 重放的数据竞争；终态不可被陈旧数据降级；`beginObservation` 诚实标注 "observation 不能证明还是同一 execution stage"
- `backend-client.ts` — BackendSession/BackendClient，与后端 contracts 对齐的判别联合类型
- approval-decisions / observation-recovery / stream-recovery / usage-settlement——断线重连和 HITL 的完整前端半圆
- Tauri 能力：workspace file open、系统托盘、后端日志

**测试**：28 个 .mjs 测试文件覆盖重连、重建、审批草稿恢复、用量结算、分页、可见性轮询。WSL 下 4 个文件因 esbuild 平台二进制失败（环境问题，非代码），Windows 下全绿。

**Evidence**: `frontend/src/`（40+ 文件）, `frontend/tests/`（28 文件）, `frontend/design.md`

**Implications**: MISSION.md 的 "Success looks like" 全部达成。项目达到 v1.0 候选状态。下一步：release、真实用户、性能观测。
