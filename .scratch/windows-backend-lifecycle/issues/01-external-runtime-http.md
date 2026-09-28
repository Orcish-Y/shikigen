# 让 HTTP 应用接入外部持有的 runtime（前置重构）

Status: ready-for-agent

## Parent

[Windows 桌面应用与后端生命周期 PRD](../PRD.md)。本票范围服从 PRD 的最终接口契约；ready-for-agent 表示信息可实施，代码仍由用户主导，助手实现需另行委托。

## What to build

调用方可持有共享 runtime，并将其交给 HTTP 应用使用；手动 HTTP 入口继续自行管理资源。为桌面启动器统一负责初始化与退出提供边界，避免重复装配。

**接口与设计原因：** 复用 open_runtime()、FastAPI lifespan 与 app.state.runtime；调用方拥有上下文时，HTTP 应用只使用该 runtime，不重复创建或关闭它。具体构造接口由实现者决定。

## Acceptance criteria

- [ ] 外部持有一个 runtime 时，Thread、Run 等现有 HTTP 路由使用同一实例，真实业务请求可成功完成。
- [ ] 托管 HTTP lifespan 不重复调用 open_runtime()，也不提前关闭调用方拥有的资源；调用方退出上下文后完成清理。
- [ ] 手动 HTTP 入口仍通过共享上下文自行装配、恢复及释放 runtime，启动或请求失败不遗留本入口已打开的资源。
- [ ] 共享 runtime 不依赖 FastAPI，CLI 继续可独立工作。
- [ ] 复用已有 lifespan、HTTP 和 runtime 测试，覆盖两种所有权方式的可观察行为；不改变现有业务 API 与持久化语义。

## Blocked by

无 — 可立即开始。

## Comments

- 2026-09-28：按用户确认的 10 票拆分发布。对应验收随本票完成，记录自动测试、Windows 原生验证与未验证项；不得将模拟进程结果代替平台验证。

