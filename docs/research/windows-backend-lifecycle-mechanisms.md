# Windows 后端托管与运行数据独占：机制调查

日期：2026-09-28。范围：[验证后端托管与数据独占的底层机制](../wayfinder/windows-backend-lifecycle/tickets/003-mechanism-research.md)。
产品行为依据：[托管接口讨论记录](../archive/README.md#windows-历史与验收)。
本报告只记录文档、源码事实和设计建议；未实现产品代码、未安装锁库、未运行 Windows 行为测试，也未验证 macOS 托管实现。

## 结论与版本边界

已确认的行为有可行的 API 组合，但不能把“发出退出请求”“主进程退出”“进程树清空”当成同一个完成条件。
建议采用创建时关联 Job、Python 保留已绑定 socket、独立启动控制器，以及覆盖全部持久存储路径的原生文件锁。
接口票可以据此收敛契约；故障注入和平台验收仍属于后续实现工作。

| 检查对象 | 本次依据 | 限制 |
| --- | --- | --- |
| Python | `.venv/pyvenv.cfg` 为 CPython 3.12 | 未确认 patch 版本 |
| Uvicorn | 本地安装源码、metadata 与 `uv.lock` 均为 0.52.1 | 内部生命周期行为升级时需复核 |
| FastAPI / Starlette | 本地 metadata 与锁文件为 0.141.1 / 1.6.0 | 未做 HTTP/SSE 集成实测 |
| Tauri | `frontend/src-tauri/Cargo.lock` 为 2.11.6 | 不能据此断言托管适配器已实现 |
| Windows Rust bindings | 锁文件含 `windows` 0.61.3、`windows-sys` 0.45 / 0.59 / 0.61.2 | 是传递依赖；尚未选定直接依赖和 features |
| 文件锁候选 | 阅读 Portalocker 固定 `v3.2.0` 源码 | 非已安装版本，非“最新版本”推荐 |

本地版本依据：[Python 锁文件](../../uv.lock)、[Rust 锁文件](../../frontend/src-tauri/Cargo.lock)、[Rust 直接依赖](../../frontend/src-tauri/Cargo.toml)。
Uvicorn 源码依据：[本地 server.py](../../.venv/Lib/site-packages/uvicorn/server.py)、[本地 lifespan/on.py](../../.venv/Lib/site-packages/uvicorn/lifespan/on.py)。
本地虚拟环境链接用于本工作区复核，不要求纳入版本控制。

## 1. Windows 进程归属与回收

### 可确认事实

`CreateProcess(CREATE_SUSPENDED)` 后再 `AssignProcessToJobObject` 仍有宿主死亡窗口：
进程已经创建，但还没有纳入 Job；挂起只阻止运行，不能让这个进程自动消失。
Microsoft 给出的创建时方案使用 `STARTUPINFOEX` 和 `PROC_THREAD_ATTRIBUTE_JOB_LIST`，在创建过程中完成 Job 关联。
该属性要求 Windows 10 或更新系统。[Microsoft 创建时关联 Job 说明](https://devblogs.microsoft.com/oldnewthing/20230209-00/?p=107812)

属性列表通过 `InitializeProcThreadAttributeList` / `UpdateProcThreadAttribute` 构造。
`PROC_THREAD_ATTRIBUTE_HANDLE_LIST` 可以限制继承句柄；它和 Job 列表承担不同职责。
使用扩展启动信息时需设置 `EXTENDED_STARTUPINFO_PRESENT`；Job 列表句柄需要文档规定的权限。
[UpdateProcThreadAttribute](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-updateprocthreadattribute)

句柄白名单限制的是本次创建的子进程。如果宿主内另一个线程以全量继承方式创建其他进程，仍可能继承临时标成可继承的管道端点。
平台实现应缩短这些端点的存活窗口并检查其他创建路径；不能把白名单视为全进程继承隔离。
[Microsoft 对并发句柄继承的说明](https://devblogs.microsoft.com/oldnewthing/20200306-00/?p=103538)

`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` 在最后一个 Job 句柄关闭时终止关联进程。
普通子进程默认随父进程归属 Job；breakaway 设置、嵌套 Job 和不同创建机制会影响边界。
因此 Job 必须由宿主独占持有可存活的句柄，不能让 Python 或其后代继承 Job 句柄。
Job 不应开放 breakaway 能力；外部独立服务不属于该树。
[Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)

`TerminateJobObject` 提供对整个 Job 的终止操作；这是强制终止，不执行正常应用清理。
API 返回成功不等于已经观察到全部进程退出。
[TerminateJobObject](https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-terminatejobobject)

`QueryInformationJobObject` 的 `JobObjectBasicAccountingInformation` 提供 `ActiveProcesses`。
它可以用于确认这个 Job 内活动进程数为零，避免仅凭 Python 主进程句柄判断整棵树结束。
[JOBOBJECT_BASIC_ACCOUNTING_INFORMATION](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_basic_accounting_information)

### 建议顺序

1. 创建本次启动专属、非继承的 Job，并配置 kill-on-close。
2. 创建三条标准流管道，宿主端禁止继承；只将 Python 所需端点加入继承白名单。
3. 准备 Job 列表和句柄列表，以 `CreateProcessW` 创建 Python；成功返回即必须已归属 Job。
4. 关闭宿主持有的子端副本，保留宿主控制端、输出读取端、进程句柄和 Job 句柄。
5. 任何部分失败都在适配器内部关闭资源、回收已创建成员；上层不能接收“半托管实例”。
6. 正常退出先发控制命令；期限耗尽则 `TerminateJobObject`，继续持有 Job 句柄查询清空。
7. 确认主进程结束且 `ActiveProcesses == 0` 后才允许下一次启动，最后关闭 Job 句柄。

宿主崩溃时依赖 kill-on-close；正常路径保留 Job 句柄则有利于观察回收结果。
若主进程已经退出而子进程仍在，必须继续回收，不能报告“已停止”。
查询失败或确认超时应报告“回收未确认”，保留禁止重试状态；具体强制回收确认期限由接口票决定。
以上是设计建议，不能将 Job API 支持推导为项目已覆盖所有 MCP / 工具进程。

### Windows 验收项

- 在创建前、创建中、创建返回后、管道建立后杀死宿主，检查是否残留 Python 或工具进程。
- 工具再派生孙进程、主进程先退出、宿主处于现有 Job 等情形都要验证。
- 验证 Job 句柄没有泄漏继承，且重复启动只处理本次所属进程。
- 旧 Windows 不支持属性或嵌套规则冲突时必须明确失败，不能静默退回存在空窗的路径。

## 2. 实际绑定、端口递增与 Uvicorn

### 可确认事实

Windows 的 `SO_REUSEADDR` 可能允许第二个 socket 抢占已使用地址，不能用来保证独占服务。
`SO_EXCLUSIVEADDRUSE` 应在 bind 前设置；具体冲突错误受双方绑定选项影响。
独占地址的第二次 bind 可能返回 `WSAEACCES`，因此不能把所有 10013 都解释成权限配置错误。
[Microsoft socket 选项说明](https://learn.microsoft.com/en-us/windows/win32/winsock/using-so-reuseaddr-and-so-exclusiveaddruse)

Winsock 定义 `WSAEADDRINUSE` 为 10048、`WSAEACCES` 为 10013；后者也可能表示访问禁止。
仅凭 10013 不能证明端口正在由某个应用占用，系统限制等情形需要保留原始诊断信息。
[Winsock 错误码](https://learn.microsoft.com/en-us/windows/win32/winsock/windows-sockets-error-codes-2)

本地 Uvicorn 0.52.1 的 `Server.serve(sockets=[sock])` 会将 socket 传给 `loop.create_server(sock=sock)`。
因此可以由同一个 Python 进程选端口并保留 socket，无须通过 Rust 传递 socket 或关闭后重绑。
该分支在应用 lifespan startup 完成后建立 asyncio server；端口已绑定不等于应用已经就绪。
Windows 多 worker 分支涉及 socket share；建议托管实例明确 `workers=1`、`reload=False`。
依据：[本地 Uvicorn Server](../../.venv/Lib/site-packages/uvicorn/server.py)。

### 建议契约

- 固定 IPv4 loopback `127.0.0.1`；候选端口从 `backend.port` 开始，到 65535 截止，不回绕。
- 每个候选使用新 socket；Windows 设置独占选项，绑定失败及时关闭该候选 socket。
- 10048 递增；10013 可作为“此候选不可绑定”递增，但日志必须区分“占用”与“访问禁止/保留可能”。
- 其他错误立即失败，例如无效参数、资源耗尽；不能把所有异常吞掉后扫完整段端口。
- 候选搜索受同一个 Rust 启动期限约束；不能按候选重新计时。
- 成功后保留同一个 socket，报告实际地址；明确交给 asyncio server 前后的资源所有者和失败关闭责任。
- 保留 `/health/ready` 加本次启动标识校验；端口消息只表示地址确定。
- macOS 适配 socket 选项，保持相同绑定语义；不复用 Windows 专有常量。

需要验收普通占用、独占占用、系统排除端口、候选耗尽和快速退出重启。
这些机制没有保证默认 43127 必然空闲，也没有保证任意 socket 错误都能靠递增解决。

## 3. 控制管道、初始化取消与 SSE 关闭

### 可确认事实

重定向标准输入输出可由父子进程管道实现，宿主应关闭多余的继承端副本。
多留一个 stdin 写端会影响 EOF 观察；控制流应只属于本次托管关系。
[Microsoft 标准流重定向示例](https://learn.microsoft.com/en-us/windows/win32/procthread/creating-a-child-process-with-redirected-input-and-output)

本地 `open_runtime()` 在 yield 前打开聊天库、checkpoint、加载 MCP、创建 Agent 并执行恢复。
其 finally 调用 `runtime.lifecycle.shutdown()`，再退出外层存储上下文。
因此必须在初始化前启动控制监听，不能等 runtime 成功 yield 后才开始读退出命令。
依据：[runtime 装配](../../packages/harness/shikigen/runtime/composition.py)。

Uvicorn 0.52.1 的 lifespan startup 会创建独立 `main()` task，再等待 startup event。
设置 `server.should_exit=True` 不会打断这个 startup 等待。
直接取消 `serve()` 也不能被当成可靠清理方案：`_serve()` 未用 finally 包住 shutdown，lifespan task 又是独立任务。
依据：[lifespan 实现](../../.venv/Lib/site-packages/uvicorn/lifespan/on.py)、[Server 实现](../../.venv/Lib/site-packages/uvicorn/server.py)。

Uvicorn shutdown 顺序为停止监听、请求连接关闭、等待连接和请求任务、最后发送 lifespan shutdown。
`timeout_graceful_shutdown` 约束连接/任务等待，不是完整 runtime 清理的总期限。
现有 `ApplicationLifecycle.shutdown()` 停止接收创建操作，等交接后关闭 ExecutionRegistry。
后者取消执行并等待收尾，finally 关闭 stream；如果只在 lifespan 最后触发，SSE 可能一直占着前面的等待阶段。
依据：[生命周期](../../packages/harness/shikigen/runtime/lifecycle.py)、[执行资源](../../packages/harness/shikigen/core/execution.py)。

### 建议协调方式

1. 托管入口首先建立控制读取和停止事件，再开始 socket / runtime 初始化。
2. stdout 仅逐行 JSON 并及时 flush；stderr 持续被宿主读取，避免日志管道填满造成阻塞。
3. shutdown 命令或 stdin EOF 进入同一个幂等停止流程；EOF 只适用于托管模式。
4. 初始化期间由控制器持有可取消的初始化 task；取消后等待已进入资源上下文退出，不直接丢弃 task。
5. 若继续由 ASGI lifespan 持有 runtime，必须显式协调其初始化任务；不能仅取消外侧 `serve()`。
6. 另一可行方向是托管控制器持有 `open_runtime()`，向 HTTP app 注入 runtime；两种入口必须确保只有一个资源所有者。
7. 已就绪时先封住新工作入口、触发 runtime shutdown，并要求 Uvicorn 停止监听；让执行停止和 stream 关闭先推动 SSE 结束。
8. 保持数据库连接到请求和执行收尾完成后才关闭；最后释放数据锁，再结束 Python。
9. 初始化不可取消、清理卡住或事件循环阻塞时，Rust 的统一退出期限到点后强制回收。

第 5、6 项是实现选择，研究结论不替用户决定具体重构方式。
可用独立读取线程将管道消息通过 `loop.call_soon_threadsafe` 送入事件循环；线程结束也要纳入设计。
不要把永远阻塞的 `stdin.readline()` 放进默认 executor 后假定 asyncio 退出会自动打断它。
需要明确管道关闭/读取退出机制；不要求跨平台采用同一个底层 I/O 实现。
[Python 线程安全调度](https://docs.python.org/3.12/library/asyncio-eventloop.html#asyncio.loop.call_soon_threadsafe)、[默认 executor 关闭](https://docs.python.org/3.12/library/asyncio-eventloop.html#asyncio.loop.shutdown_default_executor)。

推荐在 Rust 发出最终 shutdown 命令并完成写入后关闭 stdin 写端，使读取者可观察 EOF 并结束；命令和 EOF 合并为幂等退出请求。
Python 自发退出时也要通知宿主关闭写端，或使用可停止的读取机制。取消读取协程不等于中止底层阻塞线程，这一分支必须验收。

### 验收项

- 在 MCP 初始化、恢复进行中及刚转就绪时分别发送 shutdown / EOF，观察资源归还和无迟到 ready。
- 保持 SSE 连接并退出，验证正常清理在 10 秒总预算内有机会执行。
- 初始化同步阻塞、执行取消不响应、日志大量输出时，验证宿主超时仍能回收。
- 清理确认消息只供诊断；最终成功以进程及 Job 清空观察为准。

## 4. 运行数据独占：原生锁与路径集合

### 可确认事实与候选

Windows `LockFileEx` 支持独占及立即失败；进程结束或句柄关闭时系统释放锁，但释放可能存在延迟。
因此强杀后暂时获取失败可以存在，不能靠删除锁文件“修复”。
[LockFileEx](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-lockfileex)

Apple `flock` 提供 `LOCK_EX | LOCK_NB`；它是协作式锁，所有使用者必须遵守。
锁与打开的文件关联，相关描述符关闭后释放；继承/复制描述符会影响持有时间。
[Apple flock 手册](https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man2/flock.2.html)

具体候选为 Portalocker `v3.2.0`：Windows 显式使用 `Win32Locker`，依赖 pywin32；POSIX 使用 `fcntl.flock`。
该 tag 的 Windows 默认实际是 `MsvcrtLocker`，不能把默认 API 描述成 LockFileEx；文件顶部注释并不足以证明默认分支。
选择显式后端能让本报告验证的原生语义与实现对应；升级版本需复核 API，不把此 tag 当最新版。
建议封装实例而非修改全局 `LOCKER`。本项目未安装、未测试此候选，依赖选型作为建议提交接口票确认。
[Portalocker 固定版本源码](https://raw.githubusercontent.com/wolph/portalocker/v3.2.0/portalocker/portalocker.py)

本地配置独立暴露 `database.path` 和 `checkpointer.path`；默认相同，但用户可以分别修改。
checkpoint 还支持 memory 模式；它不应产生跨进程持久锁需求。
[配置模型](../../packages/harness/shikigen/app_config.py)、[checkpoint provider](../../packages/harness/shikigen/checkpoint/provider.py)

### 建议锁协议

1. 在共享 `open_runtime()` 打开任何数据库、建表或恢复之前，计算全部持久资源路径。
2. 对聊天库及 sqlite checkpoint 各自建立一个稳定的旁路锁文件；相同资源去重。
3. 统一绝对路径、用户目录展开及符号链接解析规则，并使用同一工作目录基准。
4. 按稳定顺序非阻塞取得整个锁集合；任一冲突则释放本次已得锁，报告数据正在使用，不开始恢复。
5. 权限、目录和文件系统错误单独报告，不能全部伪装成“已有应用运行”。
6. 锁持有贯穿初始化、运行、执行清理及数据库连接关闭；最后才解锁并关闭句柄。
7. 锁文件可以长期存在，不删除、不替换；存在本身不表示被锁，PID 内容也不作为权威。
8. 禁止锁描述符泄漏给工具进程；不使用基于文件存在与陈旧 PID 判断的软锁。

仅锁“两个路径拼成的配置组合”是不够的：A 使用聊天库 X / checkpoint Y，B 使用聊天库 Z / checkpoint Y 仍会冲突。
按资源分别锁定可覆盖完全相同、仅聊天库重叠、仅 checkpoint 重叠，以及角色互换的重叠情况。
同一文件作为两种存储使用时去重，避免对自己重复争锁。

路径字符串规范化不能自动解决硬链接、Windows 文件别名、网络盘和运行中重命名。
建议第一版明确支持本地稳定数据路径；对别名需检测拒绝或采用文件身份方案，不能宣称 `resolve()` 已覆盖所有同文件路径。
旁路锁文件名必须从规范化资源身份稳定派生，所有入口共用；只改桌面入口不满足独占要求。
SQLite 自身的事务锁不替代这里的 runtime 所有权锁：本需求还保护启动恢复和本进程执行归属。

### 验收项

- 同库双启动、单边路径重叠、相对/绝对路径、大小写与符号链接别名、memory checkpoint。
- 初始化失败、主动退出和强杀后重新获取；部分取得锁后失败不应泄漏已得锁。
- 锁文件残留但无锁时允许启动；有锁时禁止通过删除文件强行接管。
- Windows 原生锁和未来 macOS 原生锁分别验收，不将一个平台结果外推。

## 5. 对公共接口与剩余决策的约束

公共平台接口应返回拥有完整资源责任的托管实例，不泄漏 Job / HANDLE 到 React 或公共状态机。
至少分清“请求退出已发送”“后端主进程退出”“所属进程全部回收”；仅最后一项解锁重试。
启动的 60 秒和正常退出的 10 秒均由 Rust 单调时钟监督，Python 不能重置预算。
强制回收确认超时是独立契约，研究没有擅自新增配置默认值。
启动标识用于关联本次状态，不自动成为 HTTP 认证凭据。

尚需接口票收敛：强制回收确认期限与失败状态、控制消息字段/大小/版本错误、初始化资源所有者和最终页面状态载荷。
上述机制支持未来平台替换，但 macOS 的宿主崩溃后整树回收仍须独立设计，不能仅靠方法名一致就宣称等价。
