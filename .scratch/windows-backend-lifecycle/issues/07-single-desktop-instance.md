# 重复打开只唤起已有桌面实例

Status: done

## Parent

[Windows 桌面应用与后端生命周期 PRD](../PRD.md)。本票范围服从 PRD 的最终接口契约；ready-for-agent 表示信息可实施，代码仍由用户主导，助手实现需另行委托。

## What to build

无论后端启动中、已就绪还是失败，重复打开都进入已有桌面实例；退出中的实例保持退出，不创建第二份后端。

**接口与设计原因：** 使用 Tauri Single Instance 插件，在后端启动之前完成实例检查；已有实例处理恢复窗口和聚焦请求，读取 BackendManager 状态及退出意图。

## Acceptance criteria

- [x] 单实例检查先于任何后端创建；第二实例只通知既有实例后退出，不装配自己的 runtime。
- [x] 已有实例启动中或失败时恢复并聚焦窗口，仅展示状态，不隐式重试；ready 时恢复现有会话。
- [x] 已有实例退出中不取消退出，不创建后端；通知与状态变化交错时仍遵守退出意图。
- [x] Windows 验证同时启动、启动中重复打开、失败时重复打开、退出中重复打开；统计只有一份托管后端。
- [x] 本票可在第 4 票的启动和基础退出路径上验证实例行为；完整卡住退出流程由第 5 票负责，托盘组合由第 8 票验收。

## Blocked by

- [打开桌面应用，看到受托管后端就绪](04-desktop-managed-startup.md)

## Comments

- 2026-09-28：按用户确认的 10 票拆分发布。对应验收随本票完成，记录自动测试、Windows 原生验证与未验证项；不得将模拟进程结果代替平台验证。
- 2026-10-02：用户授权实施第 07 票。实现、两路代码审查、完整回归和真实窗口验收完成，标记 `done`。固定基线 `10805616794bef9bf4508030c2f255cbeac350a0`，工作区起始干净；未修改 Git 暂存区或创建提交。

## 实现说明

### 先取得桌面实例资格，再创建后端

Tauri Single Instance 作为第一个应用插件注册，在 `Builder::build()` 中检查实例；`BackendManager::start()` 仍在后续 `App::run()` 的应用 `setup` 中调用。普通第二实例由插件通知已有实例后直接退出，不加载自己的后端配置，也不创建 Python。

依赖固定为 `tauri-plugin-single-instance = 2.4.5`，适配已有 Tauri 2.11。Windows 增加 `StartupGuard`，通过 `CreateMutexW` / `WaitForSingleObject` 串行保护插件初始化，防止两次打开交错在“插件 mutex 已存在、通知窗口尚未建立”的间隙。句柄不继承，使用 `OwnedHandle` 管理；正常释放和进程直接退出后的 abandoned mutex 均可继续接管。

审查发现最终退出也会造成“mutex 存在、通知窗口已销毁”。因此 `build` 返回后、创建窗口和后端前，再用 `FindWindowW` / `GetWindowThreadProcessId` 验证通知窗口确属当前进程；失败则结束本次打开。详细依据、30 秒启动保护期限及升级约束见[新增机制决策](../../../docs/wayfinder/windows-backend-lifecycle/tickets/004-single-instance-startup-race.resolution.md)。

### 重复打开只操作现有窗口

插件回调经 Tauri 异步执行器投递回主线程，执行时读取 `BackendManager::is_shutting_down()`。没有退出意图时调用 `show()`、`unminimize()`、`set_focus()`，恢复隐藏或最小化的主窗口；不重建页面，不调用 `retry_backend`。

退出意图独立于快照中的状态字符串。退出时清理未确认也会显示 `failed`，仍必须继续退出，不能作为普通失败窗口重新唤起。初始准备阶段若通知到达时尚未安装 manager，由初始可见窗口正常展示接管。

验收 example 接收独立 Tauri context，应用标识使用 `dev.shikigen.desktop.acceptance`，生产仍为 `dev.shikigen.desktop`；测试不会向用户正在运行的实际应用发送通知。

## 测试边界

沿用 PRD 已确认的公开 BackendManager 状态、真实 Windows 进程及 Tauri 窗口边界。使用隔离项目与验收应用标识，覆盖 ready、starting、failed、显式退出中及同时打开；通过真实入口计数确认没有第二份配置装配或 Python，不依赖数据库锁替单实例机制兜底。验证隐藏/最小化恢复、实际前台窗口、原有启动标识及页面会话保留。

TDD 首次运行：接入插件前，`test_ready_reopen_restores_existing_window_and_session` 因第二实例 10 秒内未退出而失败；测试拥有的进程和数据已清理。

审查修复的第二轮 TDD：真实命名 mutex 存在、通知窗口缺失时，实际 Tauri 在修复前没有退出；补通知窗口所有权检查后，该入口正常退出，配置装配及 Python 计数均为 0。这里直接构造的是退出竞争的关键 Windows 状态，不声称穷举或稳定命中了全部线程调度。

## 验收结果

| 验证 | 结果与证据 |
| --- | --- |
| 真实 Windows 单实例与窗口 | 6 项通过，50.500 秒。[日志](../test-results-07-single-instance.log) |
| Rust 全套 | 19 项通过：配置 2、管理器 8、重试 3、关闭 4、原生进程 2。[日志](../test-results-07-rust.log) |
| Python 全套 | 262 项：261 通过、1 因 Windows 符号链接权限跳过，261.031 秒。[日志](../test-results-07-python.log) |
| 既有 Windows 原生回归 | 6 项通过，43.186 秒；覆盖宿主/后端异常终止、工具回收、独立入口及卡住清理。[日志](../test-results-07-native.log) |
| 前端状态回归 | 5 项通过。[日志](../test-results-07-client.log) |
| 静态检查与构建 | 所有 Rust 目标检查、`cargo fmt --check`、新增 Python 验收脚本 Ruff、TypeScript 与 Vite 构建通过；两个验收入口构建通过。[前端构建日志](../test-results-07-build.log) |

真实窗口验收由 [single_instance_acceptance.py](../../../frontend/src-tauri/tests/single_instance_acceptance.py) 自动驱动 Win32 和 WebView2，不是模拟 UI；没有另行声称人工点击验收。

| 场景 | 观察结果 |
| --- | --- |
| 8 个进程同时打开 | 仅一个宿主加载配置、一个 Python 入口启动；其余 7 个进程退出码均为 0；真实健康响应匹配唯一 startup_id |
| 初始化中重复打开 | 隐藏并最小化后恢复、聚焦；仍为原 starting 快照，Python 计数为 1 |
| 就绪时重复打开 | 恢复同一窗口和页面 JS 会话，快照、健康标识保持不变；真正退出后可再次正常启动，得到新 startup_id |
| 失败时重复打开 | 已修正磁盘配置也不自动重试；保持原失败快照，Python 计数为 0，用户仍需手动重试 |
| 退出及回收未确认时重复打开 | 两次重复打开均退出，不唤起隐藏窗口、不增加后端；重试命令继续拒绝，观察恢复后原宿主完成退出 |
| 旧通知窗口已消失 | 真实遗留 mutex 条件下不创建窗口或后端；遗留句柄释放后，后续正常打开和重复唤起继续满足单实例规则 |

各场景的状态、计数和 PID 见[验收资产目录](../single-instance-acceptance/)。已检查截图：[失败窗口](../single-instance-acceptance/test_failed_reopen_does_not_retry_even_after_configuration_is_fixed/window.png)、[就绪窗口](../single-instance-acceptance/test_ready_reopen_restores_existing_window_and_session/window.png)、[初始化窗口](../single-instance-acceptance/test_starting_reopen_only_shows_current_initialization/window.png)。焦点通过 Win32 `GetForegroundWindow` 断言，截图仅记录展示内容。

清理未确认场景沿用 example 的 Job 查询故障注入，恢复后查询真实 Job；其余进程、管道、窗口、健康 HTTP 和配置文件均实际运行。验收宿主、测试服务及隔离目录均已清理。

## Standards

做得好：原生句柄通过 RAII 管理，mutex guard 限制跨线程移动；平台细节集中在单实例模块，测试标识与生产隔离。

需要修：修复前后均未发现文档规范的硬性违反；最终复核无新增问题。

值得讨论：未发现需要提出的 Fowler smell 建议。插件内部窗口命名被集中封装，并有固定版本及升级复核说明。

## Spec

做得好：单实例检查早于后端创建，窗口通知执行时重查退出意图；真实平台验收覆盖状态保持、窗口恢复、并发和入口计数。

需要修：发现 1 项 P1——最终退出与再次打开交错可能使插件返回成功但没有通知窗口，进而失去后续单实例保护。已补启动前窗口所有权检查，代码复核通过，确定性回归由红转绿；剩余缺陷为 0。

值得讨论：没有在旧实例退出主线程上争用启动 guard，避免与第二实例的同步 `SendMessageW` 形成死锁。正常关闭和通知窗口销毁由既有退出流程处理。

审查汇总：Standards 0 项发现；Spec 1 项 P1 已修复并验证，剩余 0 项。

## 复现与范围

在 `frontend` 执行 `pnpm build`；在 `frontend/src-tauri` 执行 `cargo build --offline --example backend_host --example backend_window`。然后从仓库根执行：

```powershell
.venv/Scripts/python.exe frontend/src-tauri/tests/single_instance_acceptance.py
```

需要 Windows 桌面会话、5173 和 9238 空闲；验收后端从 45200 起绑定。验收脚本自动创建、清理隔离项目并将截图和结果写入本票资产目录。不要与使用同一验收标识的其他窗口脚本同时运行。

托盘与关窗驻留属于第 08 票，当前正常关窗仍请求退出；业务客户端和有限日志分别属于第 09、10 票。页面会话保持验收使用现有业务预览页面，不表示业务 HTTP/SSE 客户端已完成。未进行 macOS/Linux 原生验收。
