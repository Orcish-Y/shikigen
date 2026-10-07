# Windows 桌面后端：实施与验收摘要

整理日期：2026-10-02。Windows 生命周期 01～10 票均为 `done`，决策地图已关闭。本文浓缩早期规划、实施票和测试记录，未重新运行产品测试。准确字段和期限见 [最终接口契约](wayfinder/windows-backend-lifecycle/tickets/002-runtime-contract.resolution.md)，历史原文及原始证据见 [归档索引](archive/README.md#windows-历史与验收)。

## 当前行为与接口

| 做什么 | 为什么 | API / 模块 |
| --- | --- | --- |
| Rust 壳拥有 Python 后端生命周期，页面消费状态 | 刷新页面不重复启动，前端离开不结束任务 | `BackendManager`，`get_backend_state`、`backend-state`、`retry_backend` |
| 创建时关联 Windows Job，宿主独占句柄 | 消除创建后再归属的孤儿窗口，宿主异常退出回收后代 | `CreateProcessW` / `PROC_THREAD_ATTRIBUTE_JOB_LIST`、kill-on-close |
| Python 先建立控制监听、绑定 socket，再初始化 runtime | 启动中可以退出，不因端口探测留下重绑竞争 | `app/desktop.py`、`app/desktop_control.py`、`open_runtime()` |
| 独占实际持久数据路径，最后才释放锁 | HTTP、CLI 和桌面不能同时恢复/写入同一数据 | `runtime/runtime_data.py`、原生数据锁，见 [指导](windows-runtime-data-ownership.md) |
| 每次启动有唯一 startup_id 与递增 revision | 迟到 ready、状态查询、HTTP/SSE 和日志不能污染新启动 | 快照过滤、启动取消信号、`BackendSession` |
| 正常关窗隐藏到托盘，显式退出受控清理 | 后台执行持续，退出有明确边界 | 单实例插件、Tray 菜单、永久退出意图 |
| 错误页按需查看最近 1 MiB stderr | 有界诊断，日志查询不阻碍退出或重试 | `StartupLogs`、`get_backend_logs`、`BackendLogs.tsx` |

开发态直接启动项目 `.venv/Scripts/python.exe`，加载根目录 `.env`，托管模式不使用 reload。Windows 桌面最低要求来自现有契约的 Windows 10；安装包 Python 分发另行设计。配置键 `backend.port` 和 CLI `--port` 表示起始端口，默认 43127；运行时使用 `start_port`，绑定结果使用 `bound_port`。监听绑定和 CORS 来源策略位于 `app/desktop_network.py`：实际绑定 `127.0.0.1`，占用后递增，保留绑定 socket 交给 Uvicorn。控制消息 `bound.port` 传递实际端口。`bound` 不等于 ready；`/health/ready` 必须匹配本次 startup_id。

Python 和 Rust 的后端配置测试共用 `tests/fixtures/desktop_backend_config_cases.json`，核对默认值、端口范围、期限、非法类型及错误信息不回显输入值。Vite 仍由其 SDK 绑定并选择开发端口；实际前端 origin 由启动协调器传给后端 CORS。

启动期限默认 60 秒，正常清理默认 10 秒，强制回收确认最多 5 秒；本次启动沿用配置快照，不按步骤重新计时。发送 shutdown、主进程退出、所属进程树清空是不同结果。回收未确认时禁止重试并继续观察；显式退出意图不会因为进入 failed 状态而丢失。

stdout 为有长度限制的逐行 JSON 控制协议，stderr 为普通日志。日志缓存上限针对原始字节，IPC 文本转换会有额外临时内存；坏 UTF-8 使用替换字符。新启动立即换空缓存，旧管道继续排空但不能写入新缓存。

桌面 ready 后读取真实 Thread、消息、Run 和用量，通过 POST 显式发送、GET SSE 恢复观察；刷新、换端口、重试不重发消息。切换会话关闭观察连接而不取消任务。Run 当前状态以 metadata 为准，历史审批暂停事件不能覆盖已经恢复的 running。浏览器直接打开仍保留示例预览，审批提交界面未在第 09 票新增。

## 实施结果

| 票号 | 结果 | 后续查找位置 |
| --- | --- | --- |
| 01 | HTTP 接入外部持有的 runtime，避免重复装配 | `app/server.py`、共享 runtime、`tests/` |
| 02 | 多入口持久数据独占，部分取锁失败回滚 | [数据所有权指导](windows-runtime-data-ownership.md) |
| 03 | Python 受控启动、端口报告、就绪与 shutdown/EOF | [Python 启动器指导](windows-controlled-python-backend.md) |
| 04 | 桌面宿主启动与页面状态整合 | `frontend/src-tauri/src/backend/`、`frontend/src/useBackendState.ts` |
| 05 | 初始化取消、正常清理总期限、强制回收并确认 | BackendManager、`window_acceptance.py` |
| 06 | 手动重试、旧启动隔离和不可重试状态 | 管理器状态与后端快照、状态订阅测试 |
| 07 | 重复打开唤起原实例，保护插件初始化竞争 | [单实例竞争 resolution](wayfinder/windows-backend-lifecycle/tickets/004-single-instance-startup-race.resolution.md)、`single_instance_acceptance.py` |
| 08 | 关窗驻留、后台任务继续、托盘退出和一次性故障提示 | `tray_acceptance.py`；托盘创建失败则保留可见窗口与退出说明 |
| 09 | 真实会话、HTTP/SSE、动态地址、迟到请求隔离 | `frontend/src/backend-client.ts`、`useConversations.ts`、`client_acceptance.py` |
| 10 | 有界 stderr、按需日志、查询归属与失败隔离 | `backend/logs.rs`、`BackendLogs.tsx`、`log_acceptance.py` |

原 10 张票的实现细节、红绿过程、review 和各阶段数字在 `windows-history-and-evidence.zip` 的 `.scratch/windows-backend-lifecycle/issues/`。早期第 04 票“关闭窗口即退出”、第 07 票尚未接入托盘的描述只对应当时阶段，现行产品行为以第 08 票及最终契约为准。

## 最终验收依据

以下来自第 10 票 2026-10-02 最终记录与原始日志，不是本次归档重新执行的结果。

| 检查 | 记录结果 | ZIP 内原始文件名 |
| --- | --- | --- |
| Windows 联合验收 | 29 项全部通过，155.323 秒；日志 5、业务客户端 4、进程归属 6、单实例 6、托盘 8 | `test-results-10-windows-all.log` |
| Python 全套 | 262 项中 261 通过、1 跳过；跳过原有 Windows 符号链接权限用例 | `test-results-10-python.log` |
| Rust 全套 | 串行 23 项通过，含日志新增 4 项 | `test-results-10-rust.log` |
| 前端客户端 | 8 项通过 | `test-results-10-client.log` |
| TypeScript / Vite | `pnpm build` 通过 | `test-results-10-build.log` |
| 原生 example 构建 | `cargo build --offline --examples` 通过 | `test-results-10-native-build.log` |

这些场景使用真实 Windows 进程、Job、Python、持久化、WebView 和托盘。外部模型使用确定性 fixture；迟到响应、失败 IPC 等在测试边界注入，不能当作所有故障都在平台上自然复现。

首轮 Windows 联合验收有 16 个 failure 和 1 个 error：托盘菜单同坐标悬停未可靠触发，以及独立 HTTP 对照进程清理仍占数据库。验收设施修正鼠标移动路径、直接启动实际基础 Python 后，全套 29 项在同一次运行通过。首次失败日志 `test-results-10-windows-initial.log` 与修复记录仍在归档，避免只保留绿灯而丢失判断依据。

旧轮次 test-results、host/server 日志、result(s).json 和窗口截图已集中归档。它们用于回溯验收，不能代表当前代码总是通过。验收代码保留在 `frontend/src-tauri/tests/`，生成证据的目录可由测试重新创建。

## 复现入口

在前端目录运行 `pnpm build`。在 `frontend/src-tauri` 运行：

```powershell
cargo build --offline --examples
cargo test --offline -- --test-threads=1
```

在项目根目录运行：

```powershell
node --test frontend/tests/*.test.mjs
.venv/Scripts/python.exe -X utf8 -m unittest discover -s tests -v
.venv/Scripts/python.exe -X utf8 .scratch/windows-backend-lifecycle/run-10-windows.py
```

联合 runner 保留在原路径，依赖现有原生测试，不依赖被归档的早期临时 UI 脚本。原生验收需要真实 Windows 桌面及空闲的 5173/9238 端口；后端从 45200 起尝试，会打开隔离窗口并操作测试托盘。仅阅读归档无需启动测试。

## 尚未覆盖

安装包分发、Python 打包定位、macOS/Linux 原生生命周期、真实网络共享数据锁、崩溃后自动续跑及工具副作用幂等仍未被本轮证明。符号链接权限用例被跳过。前端完整审批/取消交互不应因已有后端 API 或可显示 interrupted 状态而标记完成。
