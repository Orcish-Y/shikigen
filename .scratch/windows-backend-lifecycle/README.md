# Windows 后端生命周期任务索引

来源：[PRD](PRD.md)。以下 10 张任务按用户确认的拆分发布；01～09 已完成，10 的状态为 `ready-for-agent`。具体状态与验收记录见各票；状态不自动授权助手编写代码。

每次从依赖均为 `done` 的 frontier 选择一票推进。`ready-for-agent` 不代表阻塞依赖已解除。

| 编号 | 任务 | 阻塞于 |
| --- | --- | --- |
| 1 | [让 HTTP 应用接入外部持有的 runtime（前置重构）](issues/01-external-runtime-http.md) | 无 |
| 2 | [让多个入口安全争用运行数据](issues/02-exclusive-runtime-data.md) | 无 |
| 3 | [通过控制管道启动、使用和关闭 Python 后端](issues/03-controlled-python-backend.md) | 1 |
| 4 | [打开桌面应用，看到受托管后端就绪](issues/04-desktop-managed-startup.md) | 2、3 |
| 5 | [初始化、执行或清理卡住时仍能完成退出处理](issues/05-bounded-shutdown-reclamation.md) | 4 |
| 6 | [故障后手动重试，并隔离新旧启动](issues/06-manual-retry-isolation.md) | 5 |
| 7 | [重复打开只唤起已有桌面实例](issues/07-single-desktop-instance.md) | 4 |
| 8 | [关窗驻留托盘，显式退出并提示后台故障](issues/08-tray-residency-exit.md) | 5、6、7 |
| 9 | [让业务 HTTP/SSE 请求跟随本次后端切换](issues/09-client-backend-switch.md) | 6 |
| 10 | [在错误页查看本次启动的有限日志](issues/10-startup-log-view.md) | 6 |

当前 frontier：**10**（01～09 已完成）。完成后根据各票的 Blocked by 和实际状态重新计算。

01 是前置重构；03 使用隔离数据验证启动器；04 整合数据独占和桌面托管。07 可基于 04 的基础退出行为验证单实例，完整退出及托盘组合由 05、08 验收。所有功能票承担自己的验证，不另设兜底测试票。

任务详情使用行为、接口及验收条件描述，不限定实现文件组织。PRD 和已完成的 Wayfinder 地图保持原状。
