# 初始化、执行或清理卡住时仍能完成退出处理

Status: done

## Parent

[Windows 桌面应用与后端生命周期 PRD](../PRD.md)。本票范围服从 PRD 的最终接口契约；ready-for-agent 表示信息可实施，代码仍由用户主导，助手实现需另行委托。

## What to build

用户请求退出后，应用在初始化中、执行中或持续 SSE 场景都能推进清理；卡住时进入强制回收，无法确认时保留错误窗口并继续观察。

**接口与设计原因：** BackendManager 统一计时，经 shutdown 协议触发 runtime.lifecycle.shutdown()；平台使用 TerminateJobObject 和 QueryInformationJobObject 确认活动进程归零，保留观察句柄。

## Acceptance criteria

- [x] 停止接受新任务并通知 Uvicorn 停止后立即开始 runtime.lifecycle.shutdown()，不等待 SSE 全部断开才清理，也不等待 Agent 自然完成。
- [x] 初始化各阶段收到 shutdown/EOF 可取消初始化并释放已打开资源，不以 runtime 完成装配为前提；请求和执行清理完成后关闭存储，最后释放数据锁。
- [x] 正常清理使用一次退出总期限，不按步骤重置。启动总期限耗尽先停止探测并保留启动超时原因，再正常清理，必要时强制回收。
- [x] Python 主进程意外退出时立即检查并回收残留后代，不再等待正常清理期限；不影响外部独立服务。
- [x] 强制回收确认最多等 5 秒，终止请求返回不等于完成；主进程退出且所属进程为零才能认定完成。
- [x] 查询失败或期限耗尽显示“无法确认后端已完全退出”，can_retry 为 false，继续观察。显式退出时保留错误窗口，后来确认完成才进入 stopped 并退出；非退出故障保持 failed 和原始原因。
- [x] 清理依次发布 stopping、按需 reclaiming，立即撤销 base_url；无资源的失败不虚构清理阶段，故障清理完成不以 stopped 覆盖原因。
- [x] 退出意图优先于迟到 ready；正常退出、初始化卡住、持续 SSE、执行中退出、Python 意外死亡及回收查询失败均有可观察行为测试。
- [x] Windows 验收观察真实进程、端口和数据锁；默认 60+10+5 秒是失败结果的等待预算，不作为系统必定终止的硬保证。

## Blocked by

- [打开桌面应用，看到受托管后端就绪](04-desktop-managed-startup.md)

## Comments

- 2026-09-28：按用户确认的 10 票拆分发布。对应验收随本票完成，记录自动测试、Windows 原生验证与未验证项；不得将模拟进程结果代替平台验证。
- 2026-09-30：用户授权实施第 05 票；实现、两路审查、全套测试和真实窗口验收完成。固定审查基线为 `5417408f80ff7d3b9363ccfee89884e4b0e405cd`，本轮未修改 Git 暂存区或创建提交。

## 实现说明

Python 的 `serve_backend()` 让 `open_runtime()` 的进入、运行与退出始终由同一个任务持有，同时等待控制通道停止事件。初始化期间收到 shutdown/EOF 会取消该任务，让已取得的存储和数据锁沿原有上下文退出；不会等待 Agent 装配完成。同步阻塞或不响应取消的清理由宿主强制回收兜底。

运行期间通知 Uvicorn 停止后立即调用 `runtime.lifecycle.shutdown()`，停止接收生命周期操作并取消执行。执行清理后等待 HTTP 请求结束，再退出 runtime 上下文，关闭 checkpoint、ChatStore，最后释放数据锁。持续 SSE 的正常关闭会收到既有 `execution_stopped` 观察结果，不会伪造用户取消的业务事实。

Rust 的 `ManagerState` 在同一把锁内保存首次退出时间、资源确认结果和状态快照。`request_shutdown()` 立即撤销地址，重复请求不重置期限；清理使用首次请求以来的一次总预算，包括离开健康探测所用的时间。无资源的失败可直接完成退出；已有资源必须同时确认主进程退出和 Job 进程数为零。未确认时保持 Job 句柄、禁止重试并继续观察，之后按退出意图决定 `stopped` 或保留原始 `failed`。

Tauri 在 `CloseRequested` 时阻止窗口提前销毁，在 `ExitRequested` 时阻止宿主提前退出。只有管理器发布 `stopped` 才真正退出。未确认错误页显示持续观察提示；`run_with_backend()` 允许验收入口注入隔离启动计划和平台故障，正式入口仍使用项目计划与原生适配器。

## 测试与 Windows 验收

| 验证 | 结果与证据 |
| --- | --- |
| Python 全套 | 260 项：259 通过、1 跳过、0 失败，283.122 秒；跳过原因是 Windows 无符号链接权限。[日志](../test-results-05-python.log) |
| Rust 全套 | 16 项全部通过：配置 2、管理器 8、关闭 4、原生进程 2。[日志](../test-results-05-rust.log) |
| 前端状态订阅 | Node 2 项全部通过。[日志](../test-results-05-client.log) |
| Windows 原生进程 | 6 项全部通过，47.539 秒；真实 Python/工具进程句柄、端口重新绑定、后继 runtime 重新取得数据锁。[日志](../test-results-05-native.log) |
| 真实 Tauri 窗口 | 未确认时保留可见错误窗口、重复关窗仍保留、恢复观察后退出码 0，并验证进程/端口/数据释放。[快照](../shutdown-ui-acceptance/results.json)、[截图](../shutdown-ui-acceptance/01-unconfirmed-window.png)、[日志](../test-results-05-ui.log) |
| 静态检查与构建 | `cargo check --offline`、Python 修改范围 `ty check` 与 Ruff、前端 `pnpm build` 的 TypeScript/Vite 构建通过；Windows 清单修复后 example 与正式 `shikigen-desktop` 二进制构建通过 |
| 两路审查 | Spec 无需修问题；Standards 无硬违反，测试故障数字命名建议已改为有名常量 |

初始化测试覆盖 ChatStore I/O、checkpoint setup、MCP 发现、Agent 装配和恢复查询五个等待位置；在原 Python 进程仍存活时重新进入真实 runtime，验证取消后可复用两份存储。独立进程测试覆盖 shutdown 与 EOF，以及保持 SSE 连接时停止未完成的模型执行。

Rust 关闭测试覆盖查询失败后继续观察、原始启动超时原因恢复、Job 已归零而主进程未退出时耗尽一次 5 秒确认预算，以及迟到健康响应不能恢复 ready、重复退出不重置期限。平台查询失败和主进程观察迟到由接口注入；真实进程、管道和 Job 仍使用 Windows 适配器，不声称操作系统自然产生了查询故障。

原生测试还覆盖同步初始化永久阻塞、执行 finally 永久等待、Python 单独被杀、宿主单独被杀，以及外部独立进程存活。前两种情况使用较短配置验证预算行为；默认 60+10+5 秒仍是呈现失败结果的预算，不是系统必定终止的保证。

## 复现与范围

在项目根执行 `.venv/Scripts/python.exe -m unittest discover -s tests -v`。在 `frontend/src-tauri` 执行 `cargo test --offline`；构建 `cargo build --offline --example backend_host --example backend_window` 后，可从根目录运行 `frontend/src-tauri/tests/native_acceptance.py` 和 `.scratch/windows-backend-lifecycle/acceptance_shutdown_ui.py`。窗口验收还需先在 `frontend` 执行 `pnpm build`，并保证 5173、9236 端口空闲。

窗口 example 曾因缺少 Common Controls v6 清单而在加载阶段退出。Tauri 的构建资源仅链接到 bin；现为 Windows MSVC examples 单独添加清单链接参数，窗口验收已通过。该控件版本要求见 [Microsoft TaskDialogIndirect 文档](https://learn.microsoft.com/en-us/windows/win32/api/commctrl/nf-commctrl-taskdialogindirect)。这属于测试入口构建修复。

手动重试由第 06 票实现，本轮 `can_retry` 仍为 false；托盘行为由第 08 票实现，当前关窗仍表示退出请求。未进行 macOS 原生验收。窗口日志中的 WebView2 类注销提示不影响本次窗口、退出码与资源释放断言。
