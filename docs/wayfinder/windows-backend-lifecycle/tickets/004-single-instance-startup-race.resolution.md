# Windows 单实例初始化竞争处理

日期：2026-10-02。对应[决策票据](004-single-instance-startup-race.md)。

## 证据

- 官方要求 Single Instance 作为第一个应用插件注册，并由回调恢复现有窗口。[Tauri 文档](https://v2.tauri.app/plugin/single-instance/)
- 本地下载并审计的 `tauri-plugin-single-instance 2.4.5` Windows 源码中，`CreateMutexW` 先于通知窗口创建；检测到 `ERROR_ALREADY_EXISTS` 后，只有 `FindWindowW` 成功才发送 `WM_COPYDATA` 并退出，找不到窗口则继续。上游当前分支仍有这一控制流。[官方 Windows 源码](https://github.com/tauri-apps/plugins-workspace/blob/v2/plugins/single-instance/src/platform_impl/windows.rs)
- 规格审查进一步发现，旧实例最终退出、销毁通知窗口也能造成上述分支。第二实例已经取得旧 mutex 的句柄，再查找窗口时窗口消失，就会继续运行但没有自己的通知窗口；其持有的旧句柄又会影响后续打开。单独保护新实例初始化不足以覆盖这条交错。
- 本仓库锁定的 Tauri 2.11.6 在 `Builder::build()` 尾部初始化插件；可见 WebView 窗口和应用 `setup` 在随后 `App::run()` 的准备阶段创建。因此保护 `build` 即可覆盖插件互斥量和通知窗口发布，不必持锁等待 Python 就绪。
- Tauri Runtime Wry 2.11.4 的 `send_user_message` 在当前线程为主线程时直接执行任务。因此单独调用 `run_on_main_thread` 不保证离开同步 Windows IPC 回调。

以上竞争窗口由源码确认；没有声称本机已稳定复现那几个 API 之间的微小时间窗口。真实并发验收用于验证应用整体行为，不能穷举所有操作系统调度。

## 决定

1. 沿用官方插件。固定 `=2.4.5`，与现有 Tauri 2.11 兼容；2.5 系列要求 Tauri 2.12，本票不升级桌面框架。`Cargo.lock` 保留原有包版本，新增插件所需依赖。
2. Windows 在创建 Tauri Builder 前，以应用 `identifier` 派生 `<identifier>-startup-gate` 命名互斥量，串行保护 `build()`。第一实例完成插件初始化后释放；后续实例此时已能发现插件的通知窗口，并由插件通知原实例、退出。Python 只在原实例的应用 `setup` 中启动。
3. 互斥句柄不继承给子进程，使用 `OwnedHandle` 自动关闭。guard 限制在取得互斥量的线程使用并释放。第二实例由插件直接退出，不运行 Rust 析构；Windows 随后授予等待方 abandoned mutex 的所有权，因此 `WAIT_ABANDONED` 同样视为取得成功。[微软等待语义](https://learn.microsoft.com/en-us/windows/win32/api/synchapi/nf-synchapi-waitforsingleobject)
4. 启动保护最多等待 30 秒；创建或等待失败则在创建后端前终止启动，不绕过保护。这个期限属于宿主初始化，不改变已约定的 Python 启动/清理期限。
5. 插件回调先投递到 Tauri 异步执行器，再转回主线程操作窗口。实际执行时检查 `BackendManager::is_shutting_down()`，允许时依次 `show()`、`unminimize()`、`set_focus()`；不调用启动或重试接口。初始化极早期尚未安装 manager 时，由正常的初始可见窗口展示接管。
6. `is_shutting_down` 读取永久退出意图。`failed` 可以表示普通故障，也可以表示显式退出但回收未确认，不能只看状态字符串决定是否恢复窗口。
7. `build()` 返回且启动 guard 仍持有时，用 `FindWindowW` 和 `GetWindowThreadProcessId` 确认插件通知窗口属于当前 PID。没有窗口或窗口属于其他进程，则清理并结束本次打开，早于 `App::run()` 中的可见窗口和 BackendManager 创建。这样不会留下缺少单实例保护的宿主；若旧实例正在最终退出，本次打开也不会接替它启动后端。该检查依赖固定插件的窗口命名协议，升级时必须复核。

不在旧实例的退出主线程上等待启动 guard：第二实例可能正持 guard 同步发送 `WM_COPYDATA`，此时旧主线程等待 guard 会形成相互等待。退出末尾的空窗口分支通过所有权校验处理。

生产使用 `dev.shikigen.desktop`。验收 example 使用 `dev.shikigen.desktop.acceptance`，两者的保护和通知命名空间独立，防止测试干扰正在运行的实际应用。

## 适用范围与验证

原生测试使用真实 Windows 进程、插件、窗口和 Python，检查同时启动 8 个实例，以及 starting、ready、failed、退出/回收未确认期间的重复打开；同时观察配置装配计数与 Python 入口计数，避免数据锁掩盖重复启动。另以真实命名 mutex 且无通知窗口，确定性制造退出竞争的关键平台状态：修复前实际 Tauri 未退出，修复后零装配、零 Python；关闭遗留句柄后，后续正常打开和重复唤起均恢复。6 项原生单实例测试全部通过，完整结果见[第 07 票验收记录](../../../windows-backend-lifecycle.md#实施结果)。

本票实施时尚未接入第 08 票托盘，关闭请求退出；第 08 票完成后正常关窗隐藏到托盘，显式退出才回收。macOS/Linux 未进行原生验证。插件或 Tauri 升级时需要复核初始化顺序、同步通知和 mutex 清理语义。
