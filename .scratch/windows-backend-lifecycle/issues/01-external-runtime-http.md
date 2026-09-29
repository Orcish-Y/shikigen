# 让 HTTP 应用接入外部持有的 runtime（前置重构）

Status: done

## Parent

[Windows 桌面应用与后端生命周期 PRD](../PRD.md)。本票范围服从 PRD 的最终接口契约；ready-for-agent 表示信息可实施，代码仍由用户主导，助手实现需另行委托。

## What to build

调用方可持有共享 runtime，并将其交给 HTTP 应用使用；手动 HTTP 入口继续自行管理资源。为桌面启动器统一负责初始化与退出提供边界，避免重复装配。

**接口与设计原因：** 复用 open_runtime()、FastAPI lifespan 与 app.state.runtime；调用方拥有上下文时，HTTP 应用只使用该 runtime，不重复创建或关闭它。具体构造接口由实现者决定。

## Acceptance criteria

- [x] 外部持有一个 runtime 时，Thread、Run 等现有 HTTP 路由使用同一实例，真实业务请求可成功完成。
- [x] 托管 HTTP lifespan 不重复调用 open_runtime()，也不提前关闭调用方拥有的资源；调用方退出上下文后完成清理。
- [x] 手动 HTTP 入口仍通过共享上下文自行装配、恢复及释放 runtime，启动或请求失败不遗留本入口已打开的资源。
- [x] 共享 runtime 不依赖 FastAPI，CLI 继续可独立工作。
- [x] 复用已有 lifespan、HTTP 和 runtime 测试，覆盖两种所有权方式的可观察行为；不改变现有业务 API 与持久化语义。

## Blocked by

无 — 可立即开始。

## Comments

- 2026-09-28：按用户确认的 10 票拆分发布。对应验收随本票完成，记录自动测试、Windows 原生验证与未验证项；不得将模拟进程结果代替平台验证。

## Implementation

- `app.server.create_app(runtime=...)` 接收外部持有的 runtime，HTTP lifespan 仅挂载和移除 `app.state.runtime`；调用方负责在 HTTP 使用期间维持 runtime 上下文，并在使用结束后关闭它。
- `create_app()` 与原有 `app.server:app` 手动入口通过 `open_runtime()` 自行装配、恢复和释放资源。共享 runtime、业务路由及持久化实现未修改。
- `tests/test_server.py` 覆盖外部 runtime 的真实 HTTP/SSE 请求、HTTP 退出后的继续执行、所有者退出后的存储关闭，以及手动入口请求失败后的清理；初始化失败清理及无 HTTP 独立进程由现有 `tests/test_runtime.py` 覆盖。
- Standards 与 Spec 两路审查均无发现。未执行真实模型/MCP 网络调用；本票不涉及 Windows Job、控制管道或托盘验证。

## Verification — 2026-09-28

- Windows / Python 3.12.13：HTTP 单文件 16 项通过；`ty check app packages/harness`、受影响文件 Ruff lint/format 及 `git diff --check` 通过。
- 全量 `python -m unittest discover -s tests`：229 项，228 项通过、1 项错误，耗时 378.447 秒。错误为 `test_approval_resume.ApprovalResumeTests.test_waits_for_previous_cleanup_and_survives_caller_cancellation` 在第 255 行等待 `settled` 的 3 秒超时。
- 对照：固定 `PYTHONHASHSEED=0`，将暂存区原版 `app/server.py` 在内存中加载后运行相同用例，与本次版本均在同一位置超时。未改动工作区文件进行回退，也未改动暂存区。该问题可在本票改动前的实现复现；根因尚未定位，本票未修改审批恢复代码或放宽超时。
- 全量原始输出保留在 `../test-results-01.log`。本票完成不代表全仓测试全绿。
