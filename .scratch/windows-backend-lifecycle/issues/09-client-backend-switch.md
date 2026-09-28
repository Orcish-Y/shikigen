# 让业务 HTTP/SSE 请求跟随本次后端切换

Status: ready-for-agent

## Parent

[Windows 桌面应用与后端生命周期 PRD](../PRD.md)。本票范围服从 PRD 的最终接口契约；ready-for-agent 表示信息可实施，代码仍由用户主导，助手实现需另行委托。

## What to build

页面的业务请求只连接本次 ready 后端；重试换端口后正确重取历史与运行状态，不显示旧启动内容，也不自动重复副作用。

**接口与设计原因：** 统一 HTTP/SSE 客户端消费 get_backend_state、backend-state-changed 的 startup_id、revision、base_url；通过现有 Thread、消息及 Run HTTP/SSE API 读取真实业务状态。

## Acceptance criteria

- [ ] 页面先订阅再查询状态，初次接收后仅接受更新 revision；所有业务请求从统一客户端取得当前 ready 地址，不各自硬编码端口。
- [ ] 离开 ready 撤销地址、停止新请求并清理旧连接；旧启动的迟到响应和 SSE 事件不能写入新启动页面。
- [ ] 重试成功后切换实际地址，重新取得 Thread、消息与 Run 状态，显示恢复后的持久事实。
- [ ] 刷新页面复用已运行后端；重试不自动重发用户消息、不重新执行失败 Run。
- [ ] 通过真实业务读取及 SSE 验证地址切换、持续连接断开、请求迟到和快照查询交错；使用确定性任务而非真实模型网络调用。
- [ ] 本票只完成生命周期所需的数据连接和恢复行为，不扩大为前端视觉重设计或其他 UI 功能。

## Blocked by

- [故障后手动重试，并隔离新旧启动](06-manual-retry-isolation.md)

## Comments

- 2026-09-28：按用户确认的 10 票拆分发布。对应验收随本票完成，记录自动测试、Windows 原生验证与未验证项；不得将模拟进程结果代替平台验证。

