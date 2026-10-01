# 故障后手动重试，并隔离新旧启动

Status: done

## Parent

[Windows 桌面应用与后端生命周期 PRD](../PRD.md)。本票范围服从 PRD 的最终接口契约；ready-for-agent 表示信息可实施，代码仍由用户主导，助手实现需另行委托。

## What to build

后端失败后用户可在确认旧资源回收后手动重试；修正配置即可重新启动，新旧启动互不污染，不自动重启。

**接口与设计原因：** retry_backend 立即返回 accepted、reason、snapshot；BackendManager 串行校验 can_retry 并接受启动，后续以 backend-state-changed 发布进度。

## Acceptance criteria

- [x] 仅确认主进程退出和全部所属进程回收且无应用退出意图时接受重试；页面缓存的 can_retry 不能替代管理器校验。
- [x] 接受后立即进入 starting，生成新 startup_id，后续异步通知；同一宿主 revision 继续递增，不因重试归零。拒绝返回原因和当前快照。
- [x] 每次重试重新读取并校验配置，固定本次 backend 快照；中途改配置不改变本次期限，下一次重试可以采用新配置。
- [x] 重复点击只产生一个后端；重试与退出竞争中退出意图优先，旧启动事件、协议消息及迟到健康结果不能改变新状态。
- [x] 非 ready 无 base_url，清理中不可重试；回收未确认继续观察，后来确认后非退出故障开放手动重试，显式退出则退出应用。
- [x] 失败保留原始错误与可读原因，页面展示真实 can_retry；不自动重启或执行旧任务。
- [x] 通过公开命令与状态测试连点、迟到事件、查询交错和退出竞争；Windows 演示一次真实故障、清理确认、修正配置和手动恢复。

## Blocked by

- [初始化、执行或清理卡住时仍能完成退出处理](05-bounded-shutdown-reclamation.md)

## Comments

- 2026-09-28：按用户确认的 10 票拆分发布。对应验收随本票完成，记录自动测试、Windows 原生验证与未验证项；不得将模拟进程结果代替平台验证。
- 2026-10-02：用户授权实施第 06 票；实现、两路审查、完整回归和真实窗口验收完成，状态更新为 `done`。验收宿主与 5173 测试服务已退出。

## 实现说明

### 管理器决定能否重试

`BackendManager::retry()` 在同一把状态锁内检查退出意图、资源回收结果、`failed` 状态和 `can_retry`。页面的按钮只是展示管理器能力，不能绕过检查。拒绝时返回 `accepted: false`、中文 `reason` 和当前 `snapshot`。

接受时立即创建新的 `startup_id`，将同一宿主的 `revision` 加一，进入 `starting`，清空旧地址和错误，关闭重试能力，再交给工作线程读取配置和启动进程。命令不等待健康检查完成。重复请求看到的已是新一轮 `starting`，因此只有一个请求能启动后端。

`finish()` 只在没有取得进程资源，或已确认主进程退出且 Job 内无进程时开放重试。查询失败时仍保留所有权并继续观察；后来确认后恢复原始错误及重试能力。存在显式退出意图时进入 `stopped`，不会开放重试。`request_shutdown()` 和重试使用同一把锁；已接受但尚在读取配置的启动，也会在创建进程前再次检查退出意图。

### 每轮配置和启动结果相互隔离

宿主保存 `PlanLoader`，正式入口传入 `LaunchPlan::development`，验收入口传入隔离项目的 `LaunchPlan::from_root`。每次启动重新读取并校验项目路径、Python 环境和配置，工作线程持有这一轮 `LaunchPlan`，端口和启动、退出期限均使用该快照。

每个工作线程持有接受请求时产生的启动标识；修改状态时再次核对标识。协议消息按标识过滤，健康检查核对响应标识。探测是同步的，旧轮次完成探测和回收后才能接受新一轮重试，因此旧健康请求不会跨过这个边界。管道队列及日志缓冲仍按轮次独立持有。

### 页面通过公开命令操作

Tauri 增加 `retry_backend`，返回 `accepted`、`reason`、`snapshot`。页面错误页显示真实 `can_retry`，未确认回收时保留禁用按钮和继续观察提示，确认后显示手动重试入口。

`subscribeBackendState()` 返回订阅控制器，统一接收事件、初始查询和重试回复；三者都遵守宿主的 `revision` 顺序。旧回复的状态和拒绝提示都不会覆盖新状态。卸载后忽略迟到回复，重试请求失败则显示可读提示。没有自动重启、重发消息或执行旧任务。

## 测试与 Windows 验收

| 验证 | 结果与证据 |
| --- | --- |
| Python 全套回归 | 262 项：261 通过、1 因 Windows 符号链接权限跳过、0 失败，342.910 秒。[日志](../test-results-06-python.log) |
| Rust 全套 | 19 项通过：配置 2、管理器 8、重试 3、关闭 4、原生进程 2。[日志](../test-results-06-rust.log) |
| 前端状态 | 5 项通过，覆盖订阅顺序、查询/事件/重试回复交错、拒绝原因和卸载后的迟到回复。[日志](../test-results-06-client.log) |
| Windows 原生回归 | 6 项通过，46.483 秒；覆盖宿主/后端异常终止、工具回收、独立入口占用数据、初始化和执行清理超时。[日志](../test-results-06-native.log) |
| 真实 Tauri 窗口 | 5 个检查通过，包含实际按钮及公开 IPC 命令、配置修正、新标识、新地址、刷新及退出释放。[快照](../retry-ui-acceptance/results.json)、[日志](../test-results-06-ui.log) |
| 静态检查与构建 | `cargo check --offline --all-targets`、`cargo fmt`、TypeScript `tsc --noEmit`、Vite 构建和修改范围 Ruff 检查通过；两个 Windows 验收入口构建通过 |

重试测试通过真实 Windows 进程/Job 和配置文件，验证配置错误不创建 Python、修正后恢复、16 个并发请求仅接受一次、命令在配置读取未完成时返回、退出取消待启动进程，以及中途修改配置不改变当前期限、下一轮使用新端口。新后端输出携带真实旧标识的协议消息不会污染新状态。第 05 票的迟到健康结果与退出竞争测试继续通过；回收未确认时新增公开重试拒绝断言，后来确认后检查恢复 `can_retry`。

窗口验收让一个独立 runtime 真实占用原数据库，桌面 Python 因 `RuntimeDataInUse` 失败。验收适配器暂时注入 Job 查询错误，观察禁用按钮和命令拒绝；恢复真实查询后，原始错误保留且重试可用。然后只修改隔离项目的数据库路径和端口，点击按钮并并发发出 16 次 IPC 请求，验证只得到一个新启动标识，健康响应与之匹配，新的 Thread 列表为空。刷新保留同一快照；关闭后通过进程句柄、端口重新绑定和后继 runtime 取得数据验证释放，独立 runtime 始终存活。

平台查询错误由测试接口注入，数据争用、Python、Job、HTTP、配置文件及 Tauri 窗口均真实运行；不声称 Windows 内核自然出现查询故障。

截图：[回收未确认时禁用](../retry-ui-acceptance/01-unconfirmed-retry-disabled.png)、[确认后可重试](../retry-ui-acceptance/02-confirmed-manual-retry.png)、[重试恢复就绪](../retry-ui-acceptance/03-recovered-ready.png)。

## Standards

做得好：重试资格检查和新快照创建在同一把锁内完成；配置按轮次加载，IPC、事件和查询共用 revision 排序，职责明确。

需要修：未发现 AGENTS.md、issue-tracker.md、domain.md 的硬性违反。

值得讨论：首启和重试原本重复初始化 `starting` 快照，已采纳建议，统一为 `BackendSnapshot::starting(revision)`。

## Spec

做得好：管理器重新校验重试资格，配置重读但当前期限固定；启动标识和 revision 分别保护管理器与页面，公开测试覆盖连点、查询交错、旧协议及退出竞争。

需要修：未发现第 06 票的缺失、错误实现或范围扩张。

值得讨论：迟到健康结果沿用已有退出竞争测试；跨重试隔离还由同步探测结束后才能确认回收的结构保证。业务客户端恢复和日志查询分别属于第 09、10 票。

审查汇总：Standards 0 个硬违反、1 个维护建议已处理；Spec 0 个问题。固定基线为 `9fe032a414af9190d9a52783478bad8152c2d877`；本轮未修改 Git 暂存区或创建提交。

## 复现与范围

在项目根执行 `.venv/Scripts/python.exe -m unittest discover -s tests -v`；在 `frontend/src-tauri` 执行 `cargo test --offline`；在 `frontend` 执行 `node --experimental-strip-types --test tests/backend-state.test.mjs`。构建 `cargo build --offline --example backend_host --example backend_window` 和前端资源后，从根目录运行 `.venv/Scripts/python.exe .scratch/windows-backend-lifecycle/acceptance_retry_ui.py`。窗口验收需要正常桌面会话，5173、9237、45320 端口空闲；脚本创建并清理隔离项目，不修改项目实际运行数据。

附加 `ty` 检查发现两个既有 Python 验收夹具有 14 条类型诊断，集中在 subprocess 可选标准流、Win32 句柄存根和配置字典推断；对固定基线重跑得到相同诊断，未作为本票已通过的检查。[基线记录](../test-results-06-typing-baseline.log)。窗口退出日志中的 WebView2 类注销提示不影响退出码与资源断言。

业务 HTTP/SSE 地址切换和状态重取由第 09 票实现，日志查询由第 10 票实现；本票页面恢复后仍展示已有的业务预览界面。当前关窗仍请求退出，托盘驻留由第 08 票实现；未进行 macOS 原生验收。
