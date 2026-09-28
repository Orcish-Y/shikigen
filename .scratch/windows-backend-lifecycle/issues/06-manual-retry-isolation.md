# 故障后手动重试，并隔离新旧启动

Status: ready-for-agent

## Parent

[Windows 桌面应用与后端生命周期 PRD](../PRD.md)。本票范围服从 PRD 的最终接口契约；ready-for-agent 表示信息可实施，代码仍由用户主导，助手实现需另行委托。

## What to build

后端失败后用户可在确认旧资源回收后手动重试；修正配置即可重新启动，新旧启动互不污染，不自动重启。

**接口与设计原因：** retry_backend 立即返回 accepted、reason、snapshot；BackendManager 串行校验 can_retry 并接受启动，后续以 backend-state-changed 发布进度。

## Acceptance criteria

- [ ] 仅确认主进程退出和全部所属进程回收且无应用退出意图时接受重试；页面缓存的 can_retry 不能替代管理器校验。
- [ ] 接受后立即进入 starting，生成新 startup_id，后续异步通知；同一宿主 revision 继续递增，不因重试归零。拒绝返回原因和当前快照。
- [ ] 每次重试重新读取并校验配置，固定本次 backend 快照；中途改配置不改变本次期限，下一次重试可以采用新配置。
- [ ] 重复点击只产生一个后端；重试与退出竞争中退出意图优先，旧启动事件、协议消息及迟到健康结果不能改变新状态。
- [ ] 非 ready 无 base_url，清理中不可重试；回收未确认继续观察，后来确认后非退出故障开放手动重试，显式退出则退出应用。
- [ ] 失败保留原始错误与可读原因，页面展示真实 can_retry；不自动重启或执行旧任务。
- [ ] 通过公开命令与状态测试连点、迟到事件、查询交错和退出竞争；Windows 演示一次真实故障、清理确认、修正配置和手动恢复。

## Blocked by

- [初始化、执行或清理卡住时仍能完成退出处理](05-bounded-shutdown-reclamation.md)

## Comments

- 2026-09-28：按用户确认的 10 票拆分发布。对应验收随本票完成，记录自动测试、Windows 原生验证与未验证项；不得将模拟进程结果代替平台验证。

