# 打开桌面应用，看到受托管后端就绪

Status: ready-for-agent

## Parent

[Windows 桌面应用与后端生命周期 PRD](../PRD.md)。本票范围服从 PRD 的最终接口契约；ready-for-agent 表示信息可实施，代码仍由用户主导，助手实现需另行委托。

## What to build

桌面宿主启动真正受 Windows Job 管理的后端，页面显示启动、就绪或失败；就绪地址只来自本次启动。页面刷新不会创建新后端。

**接口与设计原因：** BackendManager 使用平台 spawn(spec)、标准流、wait_exit()、terminate_tree()、wait_tree_empty() 接口；Windows 使用 CreateProcessW 与 PROC_THREAD_ATTRIBUTE_JOB_LIST。页面消费 get_backend_state 和 backend-state-changed。

## Acceptance criteria

- [ ] 从 env!(CARGO_MANIFEST_DIR) 的编译期目录向上两级定位项目根，使用绝对路径并检查项目元数据、配置及项目 Windows 虚拟环境 Python；cwd 为根目录，参数列表启动，不拼接 shell，不回退系统 Python。
- [ ] 缺环境或依赖显示准备说明（开发者先 uv sync）；路径失效明确报错，移动项目后需重新构建。带空格路径及不同启动 cwd 可用。
- [ ] Rust backend 配置校验与 Python 一致，每次启动固定 backend 快照，以 --port 传起始端口，退出也沿用本次期限；不声称其他配置具有跨进程原子快照。
- [ ] 每次创建独立非继承 Job，启用 JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE；进程创建时关联，不开放 breakaway，Job 句柄不传给子进程。标准流按句柄白名单继承，关闭宿主持有的子端副本并处理并发继承约束。
- [ ] spawn 只返回完整托管实例；部分失败清理半创建进程和句柄。主进程退出与全部所属进程退出分别观察，接口保留确认失败后的观察能力。
- [ ] 收到 bound 立即探测 /health/ready；每次未就绪后隔 250 ms 重试，单请求最多 1 秒，不并发、不越过启动总期限。连接失败和 503 可等待，身份、版本或格式错误立即失败并进入清理。
- [ ] 完整快照包含 state、revision、startup_id、base_url、can_retry、error；仅 ready 暴露地址。页面先订阅再查询，只接收更新 revision，刷新只读状态。
- [ ] 持续消费 stderr，避免管道反压或无限内存积累；本票只需维持安全输出处理，第 10 票补齐可查询日志体验。
- [ ] 在 Windows 验证宿主单进程被强杀后所属 Python 和工具后代被 Job 回收，外部独立服务不受影响；不能用杀整个进程树代替该测试。
- [ ] 验证桌面与独立入口争用数据时展示真实占用错误；启动/健康失败至少撤销地址并清理所拥有资源，不开放未经确认的重试。第 5 票完成完整期限与回收未确认行为，第 6 票开放手动重试。

## Blocked by

- [让多个入口安全争用运行数据](02-exclusive-runtime-data.md)
- [通过控制管道启动、使用和关闭 Python 后端](03-controlled-python-backend.md)

## Comments

- 2026-09-28：按用户确认的 10 票拆分发布。对应验收随本票完成，记录自动测试、Windows 原生验证与未验证项；不得将模拟进程结果代替平台验证。

