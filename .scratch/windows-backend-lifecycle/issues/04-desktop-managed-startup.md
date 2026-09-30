# 打开桌面应用，看到受托管后端就绪

Status: done

## Parent

[Windows 桌面应用与后端生命周期 PRD](../PRD.md)。本票范围服从 PRD 的最终接口契约；ready-for-agent 表示信息可实施，代码仍由用户主导，助手实现需另行委托。

## What to build

桌面宿主启动真正受 Windows Job 管理的后端，页面显示启动、就绪或失败；就绪地址只来自本次启动。页面刷新不会创建新后端。

**接口与设计原因：** BackendManager 使用平台 spawn(spec)、标准流、wait_exit()、terminate_tree()、wait_tree_empty() 接口；Windows 使用 CreateProcessW 与 PROC_THREAD_ATTRIBUTE_JOB_LIST。页面消费 get_backend_state 和 backend-state-changed。

## Acceptance criteria

- [x] 从 env!(CARGO_MANIFEST_DIR) 的编译期目录向上两级定位项目根，使用绝对路径并检查项目元数据、配置及项目 Windows 虚拟环境 Python；cwd 为根目录，参数列表启动，不拼接 shell，不回退系统 Python。
- [x] 缺环境或依赖显示准备说明（开发者先 uv sync）；路径失效明确报错，移动项目后需重新构建。带空格路径及不同启动 cwd 可用。
- [x] Rust backend 配置校验与 Python 一致，每次启动固定 backend 快照，以 --port 传起始端口，退出也沿用本次期限；不声称其他配置具有跨进程原子快照。
- [x] 每次创建独立非继承 Job，启用 JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE；进程创建时关联，不开放 breakaway，Job 句柄不传给子进程。标准流按句柄白名单继承，关闭宿主持有的子端副本并处理并发继承约束。
- [x] spawn 只返回完整托管实例；部分失败清理半创建进程和句柄。主进程退出与全部所属进程退出分别观察，接口保留确认失败后的观察能力。
- [x] 收到 bound 立即探测 /health/ready；每次未就绪后隔 250 ms 重试，单请求最多 1 秒，不并发、不越过启动总期限。连接失败和 503 可等待，身份、版本或格式错误立即失败并进入清理。
- [x] 完整快照包含 state、revision、startup_id、base_url、can_retry、error；仅 ready 暴露地址。页面先订阅再查询，只接收更新 revision，刷新只读状态。
- [x] 持续消费 stderr，避免管道反压或无限内存积累；本票只需维持安全输出处理，第 10 票补齐可查询日志体验。
- [x] 在 Windows 验证宿主单进程被强杀后所属 Python 和工具后代被 Job 回收，外部独立服务不受影响；不能用杀整个进程树代替该测试。
- [x] 验证桌面与独立入口争用数据时展示真实占用错误；启动/健康失败至少撤销地址并清理所拥有资源，不开放未经确认的重试。第 5 票完成完整期限与回收未确认行为，第 6 票开放手动重试。

## Blocked by

- [让多个入口安全争用运行数据](02-exclusive-runtime-data.md)
- [通过控制管道启动、使用和关闭 Python 后端](03-controlled-python-backend.md)

## Comments

- 2026-09-28：按用户确认的 10 票拆分发布。对应验收随本票完成，记录自动测试、Windows 原生验证与未验证项；不得将模拟进程结果代替平台验证。


## 第 04 票实施记录（2026-09-30）

### 做了什么，以及职责归属

- [`backend.rs`](../../../frontend/src-tauri/src/backend.rs)：从编译期项目目录定位根目录，检查项目元数据、桌面入口、配置和 `.venv/Scripts/python.exe`；严格解析并固定本次 backend 配置。移动项目需重建，环境缺失提示先 `uv sync`。Rust 不解析或加载模型密钥。
- [`process.rs`](../../../frontend/src-tauri/src/process.rs) 与 [`process/windows.rs`](../../../frontend/src-tauri/src/process/windows.rs)：平台适配接口提供标准流、主进程退出、终止 Job、确认 Job 清空。每次独立非继承 Job，设置 kill-on-close，在 `CreateProcessW` 创建时通过 Job 列表关联；不使用 shell、不开放 breakaway。标准流只继承三个子端，RAII 关闭临时句柄；失败不返回半托管实例。
- [`backend/manager.rs`](../../../frontend/src-tauri/src/backend/manager.rs)：单个宿主工作线程协调协议、健康检查与基础清理；本次 UUID 和 backend 快照固定。仅本次健康响应通过后发布地址，停止/失败撤销地址，始终禁止重试。协议行最多 64 KiB，消息队列最多 8 项；stderr 持续消费，仅保留 64 KiB 尾部供启动失败说明。
- [`lib.rs`](../../../frontend/src-tauri/src/lib.rs)：Tauri setup 只启动一次管理器，注册只读 `get_backend_state`，推送 `backend-state-changed`，普通退出请求通知管理器关闭。
- [`backend-state.ts`](../../../frontend/src/backend-state.ts)、[`useBackendState.ts`](../../../frontend/src/useBackendState.ts)、[`App.tsx`](../../../frontend/src/App.tsx)：先订阅再查询、只接收递增 revision；桌面显示启动/失败/关闭状态，就绪后显示现有页面与“后端已就绪”。网页预览保留原行为。没有页面启动后端命令。

### 关键修复和验证

测试采用 PRD 已确认的配置、管理器、客户端和原生平台边界。测试中的模型用既有确定性 Agent 替换，不调用模型网络；真实 Python、HTTP、数据库锁与 Windows Job 均实际运行。

| 验证 | 结果与覆盖 |
| --- | --- |
| `cargo test --offline` | 11 项通过：严格配置、默认值、环境缺失、配置快照；真实参数转义与回收、反复 CreateProcess 失败不泄漏句柄；管理器就绪/关闭、错误身份/版本、超长消息、旧消息、日志洪泛、启动超时与意外退出。见 [Rust 日志](../test-results-04-rust.log)。 |
| `cargo build --example backend_host --offline` 后运行 `native_acceptance.py` | 3 项通过：带空格项目路径、不同宿主 cwd；只 `TerminateProcess` Rust 宿主，Python 和工具后代退出、独立外部进程仍存活、再次启动能取得同一数据库锁；只杀 Python 后回收工具；普通独立 HTTP 入口持有 runtime 时，桌面展示真实数据占用错误且不影响独立入口。见 [Windows 日志](../test-results-04-native.log)。 |
| `node --test frontend/tests/backend-state.test.mjs` | 2 项通过：先订阅再查询、事件与旧查询交错、重复/旧 revision 过滤、卸载期间迟到监听释放。见 [客户端日志](../test-results-04-client.log)。 |
| `pnpm build`、`cargo check --offline` | TypeScript、Vite 生产构建、Rust 类型检查通过。 |
| Ruff、`cargo fmt`、`git diff --check` | 新增 Python 测试与 Rust 格式检查通过；未执行 Git 暂存或提交。 |

从红测试发现并修复：

1. Job 活动进程数归零和主进程句柄变为 signaled 存在短暂时间差；在同一确认期限内同时检查两者。
2. HTTP 200 后正文卡住也受请求/启动总期限约束，传输失败先视为未就绪，最终保留启动超时原因。
3. 旧启动消息只忽略协议内容，仍执行每轮进程观察；工具持续输出旧消息无法掩盖 Python 主进程退出。

代码审查：Standards 无必须修复项；Spec 初次发现的 2 项已修复并复核为 0。非阻塞建议是后续状态扩展时考虑 Rust 枚举。

### 验收边界

- 原生验收使用与 Tauri 相同管理器和平台适配层的 [`backend_host`](../../../frontend/src-tauri/examples/backend_host.rs) 控制台宿主，确实只杀宿主单进程，未用整树杀进程代替 Job 验证。工具后代为真实长驻 Python 进程；外部对照为独立启动的长驻进程。
- 客户端订阅边界和生产构建已验；2026-09-30 补充真实 Tauri 窗口的自动化验收，使用 WebView2 CDP 刷新、读取可见状态与截图，使用主窗口 WM_CLOSE 验证退出。详见 [界面验收记录](../ui-acceptance/README.md)。
- 本票有基础正常退出、强制回收和保留 Job 继续观察。初始化取消、完整关闭期限与回收未确认时的窗口行为仍由 05 验收；手动重试由 06 实施；单实例、托盘、业务 HTTP/SSE 地址切换、可查询日志分别留 07～10。当前会话区域仍是页面框架预览。
- 当前宿主唯一新增进程创建路径都经过适配层锁和白名单；以后增加任何宿主侧启动路径时，也必须使用该适配器或明确句柄白名单。不能把本次白名单当成其他线程全量继承的隔离保证。

机制依据：[Microsoft 创建时 Job 关联](https://devblogs.microsoft.com/oldnewthing/20230209-00/?p=107812)、[UpdateProcThreadAttribute 的 Job/句柄列表要求](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-updateprocthreadattribute)、[并发句柄继承约束](https://devblogs.microsoft.com/oldnewthing/20200306-00/?p=103538)。

### 最终回归结果

现有 Python 全套 `python -m unittest discover -s tests -v`：**257 项，256 通过，1 跳过，0 失败**，耗时 224.805 秒。跳过项仍是当前 Windows 无符号链接创建权限；见 [Python 全套日志](../test-results-04-python.log)。测试未改变既有 Python 业务实现。

本地启动：先在项目根目录准备 `uv sync` 与 `config.json`，再进入 `frontend` 运行 `pnpm tauri dev`。后端源码修改后需退出桌面宿主再重开；页面刷新只重新读取状态。

并发创建核对：本地 Tauri 2.11.6 的 `app::setup` 先创建配置中的 WebView 窗口，随后执行本项目 setup 并启动管理器；当前项目没有其他宿主侧进程启动路径。适配层的互斥锁负责本接口内的并发创建，后续增加启动路径仍需遵守句柄白名单约束。

### 真实界面补充验收（2026-09-30）

自主验收通过：实际 Tauri 窗口从 starting 进入 ready；健康响应属于本次启动；连续三次页面刷新保持同一 startup_id、revision 与 Python 进程；第二个宿主显示真实数据占用错误且地址为空、不可重试；失败窗口和就绪窗口均正常关闭并退出；只 TerminateProcess 真实 Tauri 宿主后 Python 被 Job 回收，外部独立前端 HTTP 服务继续可访问。

截图发现侧栏与编辑器还使用旧的“后端未连接”文字，已让两处消费与顶部相同的就绪事实，发送按钮仍明确为界面预览。新的真实页面断言先失败、修复后通过；`pnpm build` 通过。临时 Rust 诊断日志已清除。详见 [界面日志](../test-results-04-ui.log) 和 [截图与复现方式](../ui-acceptance/README.md)。
