# 初始化、执行或清理卡住时仍能完成退出处理

Status: ready-for-agent

## Parent

[Windows 桌面应用与后端生命周期 PRD](../PRD.md)。本票范围服从 PRD 的最终接口契约；ready-for-agent 表示信息可实施，代码仍由用户主导，助手实现需另行委托。

## What to build

用户请求退出后，应用在初始化中、执行中或持续 SSE 场景都能推进清理；卡住时进入强制回收，无法确认时保留错误窗口并继续观察。

**接口与设计原因：** BackendManager 统一计时，经 shutdown 协议触发 runtime.lifecycle.shutdown()；平台使用 TerminateJobObject 和 QueryInformationJobObject 确认活动进程归零，保留观察句柄。

## Acceptance criteria

- [ ] 停止接受新任务并通知 Uvicorn 停止后立即开始 runtime.lifecycle.shutdown()，不等待 SSE 全部断开才清理，也不等待 Agent 自然完成。
- [ ] 初始化各阶段收到 shutdown/EOF 可取消初始化并释放已打开资源，不以 runtime 完成装配为前提；请求和执行清理完成后关闭存储，最后释放数据锁。
- [ ] 正常清理使用一次退出总期限，不按步骤重置。启动总期限耗尽先停止探测并保留启动超时原因，再正常清理，必要时强制回收。
- [ ] Python 主进程意外退出时立即检查并回收残留后代，不再等待正常清理期限；不影响外部独立服务。
- [ ] 强制回收确认最多等 5 秒，终止请求返回不等于完成；主进程退出且所属进程为零才能认定完成。
- [ ] 查询失败或期限耗尽显示“无法确认后端已完全退出”，can_retry 为 false，继续观察。显式退出时保留错误窗口，后来确认完成才进入 stopped 并退出；非退出故障保持 failed 和原始原因。
- [ ] 清理依次发布 stopping、按需 reclaiming，立即撤销 base_url；无资源的失败不虚构清理阶段，故障清理完成不以 stopped 覆盖原因。
- [ ] 退出意图优先于迟到 ready；正常退出、初始化卡住、持续 SSE、执行中退出、Python 意外死亡及回收查询失败均有可观察行为测试。
- [ ] Windows 验收观察真实进程、端口和数据锁；默认 60+10+5 秒是失败结果的等待预算，不作为系统必定终止的硬保证。

## Blocked by

- [打开桌面应用，看到受托管后端就绪](04-desktop-managed-startup.md)

## Comments

- 2026-09-28：按用户确认的 10 票拆分发布。对应验收随本票完成，记录自动测试、Windows 原生验证与未验证项；不得将模拟进程结果代替平台验证。

