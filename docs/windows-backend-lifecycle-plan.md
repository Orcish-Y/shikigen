# Windows 桌面应用与后端生命周期规划

日期：2026-09-24  
状态：规划已完成，尚未实现。实施以[最终接口契约](wayfinder/windows-backend-lifecycle/tickets/002-runtime-contract.resolution.md)为准。本文保留早期实施草案和验收场景，如与最终契约冲突，以最终契约为准；决策入口见 [wayfinder 地图](wayfinder/windows-backend-lifecycle/map.md)。

## 目标

启动 Tauri 单实例桌面应用时自动启动 Python 后端；关闭窗口后常驻托盘并继续运行任务，通过托盘右键菜单退出应用时清理后端；桌面宿主进程崩溃或被强杀后，后端及其所属子进程也能够退出。

第一阶段在 Windows 原生环境完成开发联调和验证。后续主要目标平台为 Windows、macOS；WSL 可继续用于独立的 Harness 开发。

## 已确认的行为

原始决策记录在[确定平台、生命周期归属与故障行为的 resolution](wayfinder/windows-backend-lifecycle/tickets/001-behavior.resolution.md)；用户后续逐项确认见[托管接口讨论记录](wayfinder/windows-backend-lifecycle/tickets/002-runtime-contract.discussion.md)，最终结论已汇总到[托管接口与状态转换契约](wayfinder/windows-backend-lifecycle/tickets/002-runtime-contract.resolution.md)。

本次“应用异常退出”指 Tauri 桌面宿主进程退出。仅页面刷新不应重复启动后端；渲染进程单独崩溃时的恢复策略不等同于宿主退出，后续再细化。

## 当前代码与缺口

- [前端启动脚本](../frontend/package.json)：`pnpm dev` 仅启动 Vite。
- [Tauri 配置](../frontend/src-tauri/tauri.conf.json)：`beforeDevCommand` 仅启动 Vite，没有启动后端。
- [Rust 入口](../frontend/src-tauri/src/lib.rs)：目前只有基础 Builder，没有后端进程管理和退出处理。
- [FastAPI 入口](../app/server.py)：已有 lifespan，通过 `open_runtime()` 管理 runtime 资源，但没有健康检查或桌面应用生命周期绑定。
- 当前手动启动后端使用 Uvicorn，开发命令带 `--reload`。这会影响进程树管理，不能只追踪一个 Python PID。

## 架构与职责

```text
Tauri Rust 壳
  ├─ 页面：展示后端状态、发起重试
  ├─ 单实例与托盘：唤起窗口、隐藏窗口、请求退出
  └─ 公共后端生命周期管理模块
       └─ 可替换的进程托管接口
            ├─ Windows 实现：Job Object（本轮）
            └─ macOS 实现（后续）
                 各平台托管 Python 后端及其 MCP / 工具子进程
```

**Tauri 壳拥有生命周期。** 启动、监控、停止和重试由同一个模块协调，页面只消费状态和请求操作。这样页面刷新不会重新创建后端，也不依赖浏览器卸载事件完成清理。

**隔离平台差异。** 用户已要求预留 macOS 可替换接口。建议公共管理器保留状态、超时和控制协议，将系统进程创建与回收封装在平台实现中；具体接口草案见[托管接口讨论记录](wayfinder/windows-backend-lifecycle/tickets/002-runtime-contract.discussion.md#macos-可替换接口需求已确认)。替换实现须满足相同的行为与失败处理约定，macOS 实现及验证留待后续。

**后端拥有业务资源清理。** 正常退出应进入已有 FastAPI lifespan / runtime shutdown 流程。强制回收只保证进程终止，不能保证 Python 清理代码执行或未完成任务保存。

**Windows Job Object 负责异常回收兜底。** 候选 API 为 `CreateJobObject`、`SetInformationJobObject`、`AssignProcessToJobObject`，配合 `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`。最后一个 Job 句柄关闭时终止关联进程；必须控制句柄继承和进程归属。

实现时需避免“后端已经运行并创建子进程，但尚未纳入 Job”的竞态。仅以挂起状态创建再调用 AssignProcessToJobObject，仍有宿主在两步之间退出而留下孤儿进程的窗口；微软提供 Windows 10 起支持的 PROC_THREAD_ATTRIBUTE_JOB_LIST，可在创建时指定 Job，作为本轮优先验证的方案。来源：[Microsoft 对创建时关联 Job 的说明](https://devblogs.microsoft.com/oldnewthing/20230209-00/?p=107812)。具体 Rust 封装、句柄与失败处理见[底层机制研究票](wayfinder/windows-backend-lifecycle/tickets/003-mechanism-research.md)。

## 实施步骤

以下步骤尚未执行；代码仍由用户主导，除非另行明确委托。

| 步骤 | 做什么 | 为什么 | API / 接口方向 |
| --- | --- | --- | --- |
| 1. Windows 原生基线 | 在 Windows 本地目录准备项目和依赖，分别手动启动桌面应用与后端 | 先确认目标平台基础环境可用 | Node、Rust MSVC、C++ Build Tools、WebView2、uv / Python |
| 2. 后端启动与就绪 | 由 Rust 管理单次后端启动，等待服务就绪，记录启动错误 | 区分“进程存在”和“服务可用” | Tauri 初始化入口、进程创建 API、FastAPI 健康检查 |
| 3. 所有权与异常回收 | 将后端及其子进程纳入 Job，验证宿主强杀后的回收 | 防止遗留后台服务 | Windows Job Object API |
| 4. 正常退出 | 发起受控关闭，等待清理，超时强制回收 | 尽量完成 runtime 资源释放，同时避免退出卡住 | Tauri 退出事件、后端关闭控制通道、Job 回收 |
| 4a. 单实例与托盘 | 重复启动唤起已有窗口；关窗隐藏，托盘菜单触发受控退出 | 保持后台任务和唯一托管后端 | Tauri Single Instance、窗口事件、TrayIconBuilder 与菜单事件 |
| 5. 状态与手动重试 | 页面显示启动中、就绪、失败等状态；重试前确认旧进程已回收 | 避免重试产生多份后端 | Tauri command / event 或状态查询接口 |
| 6. 集成验收 | 在 Windows 上验证正常、异常、重复操作及进程树回收 | Linux / WSL 测试不能替代 Windows 生命周期验证 | 桌面操作、进程检查、端口检查、后端日志 |

托管启动关闭 Uvicorn reload 已由用户确认，原因与开发时生效方式见[托管后端自动重载决策](wayfinder/windows-backend-lifecycle/tickets/002-runtime-contract.discussion.md#托管后端自动重载已确认)。

## 实现前仍需明确的细节

这些是局部接口与参数选择，不改变已确认的产品行为：

- 开发态 Python 可执行文件、工作目录、配置文件和端口的解析方式。
- 健康检查的具体路径、就绪判定，以及如何确认响应来自本次启动的后端。
- 正常退出采用哪一种受控关闭通道；不能假定 Windows 与 Unix 的信号语义相同。
- 启动等待、正常退出等待和异常回收的时间上限。
- Job 句柄归属、进程创建与纳入 Job 的顺序，以及失败时的回收方式。
- 重试、显式退出、启动完成同时发生时的状态协调，以及窗口隐藏与恢复时的状态同步，防止重复启动或遗漏回收。
- 启动日志与错误如何提供给用户定位问题。

## 验收场景

- 启动一次桌面应用，只产生一份托管后端；页面刷新不会重复启动。
- 重复打开应用时唤起已有窗口，不创建第二份托管后端。
- 桌面、手动 HTTP 和 CLI 入口争用同一份运行数据时，只允许取得独占锁的 runtime 继续初始化；其他启动者报错，不执行恢复、不影响已有运行。
- 后端初始化期间有明确状态，健康检查通过后才开放操作。
- 配置错误、启动超时时显示原因；配置起始端口被占用时递增尝试，最终地址传给页面；已有独立服务继续运行。端口决策及待定边界见[托管接口讨论记录](wayfinder/windows-backend-lifecycle/tickets/002-runtime-contract.discussion.md#端口选择已确认)。
- 后端启动失败后重试能够恢复，连续点击重试不会产生多份后端。
- 后端运行中崩溃后显示错误，不自动重启；手动重试可恢复。
- 空闲时和 Agent 执行中关闭窗口，均隐藏到托盘，保留后端与现有任务；重新打开窗口不重启后端。
- 空闲时和 Agent 执行中通过托盘菜单退出，均能在约定时间内清理后端并释放端口。
- 正常退出能观察到后端清理流程；清理卡住时能够超时回收。
- 保持 SSE 连接时退出，runtime 仍有机会完成清理；不能只验证无连接的空闲退出。
- 桌面托管控制管道关闭时，Python 主动清理并退出；独立 CLI 和手动 HTTP 入口不受 stdin EOF 规则影响。
- 直接强杀 Tauri 宿主后，其后端、MCP 和工具子进程不遗留；不能仅用杀掉整个进程树的操作替代此测试。
- 启动过程中关闭窗口，初始化继续；显式退出或强杀应用，不遗留尚在初始化的后端。
- 本次应用退出或被强杀，不影响外部独立运行的服务。

## 后续范围

- macOS 生命周期适配和原生验证。
- 打包后的 Python 运行时、后端资源定位和安装包交付；开发态方案应预留启动入口替换能力。
- 后端自动重启不属于本版行为；托盘驻留与关窗后继续执行任务已由用户于 2026-09-26 纳入本轮。

## 参考资料

- [Tauri 开发前置要求](https://v2.tauri.app/start/prerequisites/)
- [Tauri Windows 安装包与交叉编译限制](https://v2.tauri.app/distribute/windows-installer/)
- [Windows Job Objects：进程组管理与关闭时回收](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)
- [WSL 与 Windows 文件系统使用建议](https://learn.microsoft.com/en-us/windows/wsl/filesystems)
