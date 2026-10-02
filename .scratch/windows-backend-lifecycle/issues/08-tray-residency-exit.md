# 关窗驻留托盘，显式退出并提示后台故障

Status: done

## Parent

[Windows 桌面应用与后端生命周期 PRD](../PRD.md)。本票范围服从 PRD 的最终接口契约；ready-for-agent 表示信息可实施，代码仍由用户主导，助手实现需另行委托。

## What to build

正常关窗后任务继续执行，用户能从托盘返回或显式退出；后台生命周期故障恢复窗口一次，提供错误和重试操作。

**接口与设计原因：** 使用 Tauri 托盘、窗口关闭及菜单事件，连接已有 BackendManager 退出和重试流程；Single Instance 唤起同一窗口。

## Acceptance criteria

- [x] 正常关窗只隐藏窗口，不设置退出意图、不停止 Python 或 Agent；启动期间隐藏也继续初始化。
- [x] 托盘左键恢复并聚焦，右键提供“打开主窗口”“退出应用”；后者调用既有受控退出与回收流程。
- [x] 托盘创建失败时保留窗口并说明原因，此时关窗执行正常退出，不使应用隐藏失联。
- [x] 隐藏时发生后端生命周期故障恢复窗口，显示原因和当前重试能力；同一次故障只恢复一次，清理进展不反复抢焦点，用户可再次隐藏。
- [x] 单个 Agent 任务失败沿用任务页面，不触发生命周期故障唤起。
- [x] 退出中重复打开不取消退出；未确认回收时保留错误窗口，后续确认后自动退出。
- [x] Windows 桌面验收空闲、执行中、初始化中关窗继续工作，以及恢复、托盘退出、托盘创建失败、后台故障和重复打开组合；验证实际任务继续推进。

## Blocked by

- [初始化、执行或清理卡住时仍能完成退出处理](05-bounded-shutdown-reclamation.md)
- [故障后手动重试，并隔离新旧启动](06-manual-retry-isolation.md)
- [重复打开只唤起已有桌面实例](07-single-desktop-instance.md)

## Comments

- 2026-09-28：按用户确认的 10 票拆分发布。对应验收随本票完成，记录自动测试、Windows 原生验证与未验证项；不得将模拟进程结果代替平台验证。
- 2026-10-02：用户明确委托实现。审查基线固定为 `bb508dea10c0b29268de770a93421954600fd082`，开始时工作区干净；未执行暂存或提交。

## 实现说明

### 做什么、为什么、用什么 API

| 做什么 | 为什么 | API / 所在位置 |
| --- | --- | --- |
| 由宿主控制托盘和窗口 | 隐藏或刷新 WebView 不应影响后端所有权 | `desktop.rs` 私有模块；Tauri `TrayIconBuilder`、`MenuItem`、`CloseRequested` |
| 关窗隐藏，保留本次 runtime | 初始化、Agent 执行和 SSE 均继续工作 | `Window::hide()`；不设置退出意图 |
| 左键及菜单恢复同一窗口 | 保留页面会话、当前错误和后端启动标识 | `show()`、`unminimize()`、`set_focus()`；Single Instance 复用 `activate()` |
| 托盘退出走既有回收流程 | 保持正常期限、Job 强制回收及继续观察规则 | `BackendManager::request_shutdown()`；收到 `stopped` 后 `AppHandle::exit(0)` |
| 同一故障只提示一次 | 用户再次隐藏后，清理进展不反复抢焦点 | 按 `startup_id` 记录首次错误，按 `revision` 过滤迟到通知 |
| 托盘不可用时显示常驻警告 | 用户知道关窗会退出，应用不会隐藏失联 | 只读 `get_tray_error`；`TrayNotice` 在状态页及就绪页显示原因 |

窗口操作集中在主线程。单实例通知仍先经过异步执行器再投递主线程，避免在同步 Windows IPC 回调中直接操作窗口。执行激活时重新检查永久退出意图；重试后排队的旧启动通知不能唤起新窗口。

显式退出会先恢复窗口，显示清理进展；退出过程中再关窗不会隐藏错误窗口。回收未确认时保留窗口、禁用重试，后续确认完成后自动退出。普通后台故障则允许用户查看后再次隐藏。

故障提示只消费 `BackendSnapshot.error`。单个 Agent Run 的 `error` 是既有 HTTP/SSE 业务终态，不会被转换成后端生命周期故障。任务页面客户端仍属于第 09 票；本票的真实任务验收通过现有 HTTP/SSE 接口进行。

### Windows 托盘注册检查

启用 Tauri 的 `tray-icon` feature，沿用锁文件中的 Tauri 2.11.6 / tray-icon 0.24.2，没有升级依赖。托盘使用应用已有图标，右键菜单为“打开主窗口”“退出应用”，左键关闭菜单弹出行为并恢复主窗口。

核对本地依赖源码发现，tray-icon 0.24.2 在 `Shell_NotifyIconW(NIM_ADD)` 失败后可能仍返回成功。因此 Windows 创建后通过公开 `TrayIcon::rect()`（内部调用 `Shell_NotifyIconGetRect`）确认注册；不能确认时移除托盘资源，保留窗口并进入关窗退出模式。缺图标、菜单构造及托盘构造错误也进入同一回退路径。

参考：[Tauri 官方托盘 API](https://v2.tauri.app/learn/system-tray/)。本票保持原规格，不增加托盘配置项或自动重试策略。

## 验收方式与证据

使用真实 `backend_window.exe`、WebView2、Windows 托盘菜单、Python 控制管道和 Job。应用标识仍为独立的 `dev.shikigen.desktop.acceptance`，配置、聊天库和 WebView 数据位于临时目录；不触碰实际运行数据。

自动化边界：关窗及托盘左右键从真实 Win32 消息入口触发；托盘右键打开原生菜单，读取并核对两项文字，再以实际鼠标点击菜单项。窗口可见性、最小化和前台窗口由 Win32 查询，页面状态与截图由 WebView2 CDP 读取。这是 Windows 桌面自动验收，不记作人工点击验收。

外部模型调用以确定性 fixture 控制，Agent Loop、HTTP/SSE 和持久化路径真实运行。回收未确认通过既有平台观察适配器注入可恢复的查询错误；托盘创建失败通过隔离 example 移除默认图标触发。没有模拟 BackendManager，也没有把该错误注入宣称为穷举全部 Windows Shell 故障。

### 红绿过程

1. 先验证空闲关窗后 HTTP 和同一 WebView 仍存在：原实现关闭了 WebView，测试失败；接入托盘驻留后通过。
2. 先验证隐藏时强杀测试 Python 会恢复错误窗口：初版窗口保持隐藏，测试失败；接入生命周期通知后通过，后续回收确认不会再次唤起。
3. 先验证托盘不可用原因出现在就绪页面：原页面没有警告，测试失败；接入 `TrayNotice` 后通过。

### Windows 场景

| 场景 | 可观察结果 |
| --- | --- |
| 空闲关窗 | 同一 `startup_id`、HTTP 健康响应及 WebView 会话保留；左键、右键菜单及重复打开均恢复并聚焦 |
| 初始化关窗 | 隐藏时继续初始化并达到 ready，只有一份后端 |
| 执行中关窗 | 关窗前任务仍在执行；隐藏后 SSE 到达 completed，HTTP 消息历史能读到已保存结果 |
| 单个任务失败 | SSE 到达 error，窗口仍隐藏，后端快照保持 ready |
| 隐藏后端故障 | 强杀 Python 后恢复窗口一次；回收未确认禁止重试，确认后开放重试且不再次恢复；手动重试后的新故障可再次提示 |
| 托盘创建失败 | 窗口可见、显示缺图标及关窗退出说明，关窗后宿主正常退出 |
| 初始化中托盘退出 | 保留回收未确认错误窗口，X 不隐藏；两次重复打开不取消退出、不创建新后端；观察恢复后自动退出 |
| 执行及 SSE 中托盘退出 | 已开始执行的任务进入清理，卡住时由既有 Job 回收；Python 和所属测试子进程均退出 |

截图：[托盘不可用警告](../tray-acceptance/test_missing_tray_keeps_window_and_explains_close_will_quit/window.png)、[退出未确认错误窗口](../tray-acceptance/test_tray_quit_during_initialization_retains_unconfirmed_error_then_exits/window.png)、[后台生命周期故障](../tray-acceptance/test_hidden_backend_failure_is_shown_once_until_next_attempt/window.png)。截图已逐张检查可读性。

## Standards

做得好：窗口与托盘职责集中，BackendManager 继续独占回收决策；激活入口和原生验收基础设施复用，锁在窗口操作和退出前释放。

需要修：没有仓库文档规范违例或需修复的 smell。

值得讨论：核对 Tauri 资源表确认托盘由应用持有，局部变量离开作用域不销毁图标。

## Spec

做得好：关窗驻留、显式退出、故障去重、创建失败回退和单实例退出优先均有实现及原生验收。

需要修：审查发现 1 项 P2 测试契约错误——将任务失败的 SSE 终态期望写成 `failed`。已按 `app/run_contract.py` 的公开契约修正为 `error`，并在联合验收中通过后续保持隐藏和 ready 的断言；生产实现无需改动。

值得讨论：验收明确区分 Win32 通知注入、真实菜单点击、平台查询故障注入与真实进程回收，不宣称已经完成 macOS/Linux 原生验收。

审查汇总：Standards 0 项；Spec 1 项 P2 测试问题已修复并验证，剩余 0 项。

## 最终验证结果

| 检查 | 结果与日志 |
| --- | --- |
| Windows 原生场景 | 共 20 项完成验证：6 项进程/回收、6 项单实例、8 项托盘。联合运行 18 项通过，2 项修正验收操作后定向复测通过；详见下文 |
| Rust 全套 | 19 项通过；[串行全套日志](../test-results-08-rust-serial.log) |
| Python 全套 | 262 项中 261 通过、1 跳过，296.350 秒；[日志](../test-results-08-python.log)。跳过原有符号链接测试，当前 Windows 权限不允许创建符号链接 |
| 前端状态订阅与重试 | 5 项通过；[日志](../test-results-08-client.log) |
| TypeScript / Vite | `pnpm build` 通过；[日志](../test-results-08-build.log) |
| 静态检查 | `cargo check --offline --all-targets`、`cargo fmt --check`、变更 Python 文件的 Ruff 检查及格式检查、`git diff --check` 通过 |

[联合 Windows 日志](../test-results-08-windows.log)保留了 20 项首轮完整结果（153.731 秒）。两项定向复测为：

- [退出中重复打开](../test-results-08-reopen-quit.log)：6.829 秒通过。原用例混入了“外部 Win32 隐藏后必须再次故障唤起”的断言，可能与已经完成的一次提示竞争；现单独验证单实例不激活退出中的宿主，正常 X 与故障恢复由托盘场景覆盖。同时不再要求轮询一定捕获到短暂的 stopping 阶段。
- [实际任务关窗后完成及托盘退出](../test-results-08-task-residency.log)：6.058 秒通过。第一次任务完成和持久化已通过，但菜单退出未完成；补充菜单坐标命中、高亮、按压间隔及关闭确认后，完整复测通过。

Rust 首次并行执行中，既有 `health_protocol_and_timeout_failures_never_publish_an_address` 在 0.6 秒启动预算内先超时，得到 startup_timeout 而不是 health_identity；单独复测及串行全套通过，没有改动产品期限或该测试的断言。[首次日志](../test-results-08-rust.log)保留现场。

新托盘截图和 JSON 结果保存在 [tray-acceptance](../tray-acceptance/)；本票的单实例回归结果保存在 [tray-single-instance-acceptance](../tray-single-instance-acceptance/)，第 07 票原有验收资产保持原样。

## 复现

先在 `frontend` 执行 `pnpm build`，在 `frontend/src-tauri` 执行 `cargo build --offline --example backend_host --example backend_window`。然后从仓库根执行：

```powershell
.venv/Scripts/python.exe -m unittest discover -s frontend/src-tauri/tests -p '*_acceptance.py' -v
```

此命令串行运行 6 项进程归属/回收、6 项单实例和 8 项托盘验收。需要 Windows 桌面会话，以及空闲的 5173、9238 端口；后端端口从 45200 起尝试。执行时会显示验收窗口及托盘菜单，不要同时运行其他使用该验收标识的窗口脚本。

第 09 票业务客户端和第 10 票日志查询仍待完成。本票没有修改后端状态协议、运行数据路径或自动重试规则。
