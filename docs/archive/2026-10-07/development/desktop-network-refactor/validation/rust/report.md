> 归档于 2026-10-07；正文状态与命令属于原开发阶段。当前完成情况见 [开发交接](../../../../../../development-handoff.md)。相对路径链接已迁移；代码块中的旧 scratch 路径需按归档路径调整。

# 桌面端网络整理：Rust 与 Node 验证报告

## 执行信息

- 验证 agent：`gpt-6-luna`，推理强度 `max`（按任务指定）。
- 工作区：`C:\code\shikigen-agent`。
- Rust cwd：`C:\code\shikigen-agent\frontend\src-tauri`；Node cwd：`C:\code\shikigen-agent\frontend`。
- Cargo、Rust、rustfmt、Node 版本：见下方版本表及 `tool-versions.txt`。
- 本 agent 只执行获批验证；日志、报告和隔离 Cargo build cache 均位于 `.scratch/desktop-network-refactor/validation/rust/`。没有修改产品源码、测试、fixture 或 Git。

## 结果

| 验证 | 结果 |
|---|---:|
| Rust 专项 `backend_config` | 3 passed，0 failed，0 ignored，退出码 0（隔离 target） |
| Rust 完整 `cargo test` | 36 passed，0 failed，0 ignored，0 filtered，退出码 0（隔离 target） |
| Node 端口协调器专项 | 9 passed，0 failed，0 cancelled，0 skipped，0 todo，退出码 0 |
| rustfmt 检查 | 通过，退出码 0 |
| 最终测试失败数 | 0 |

完整 Rust 回归包含 `backend_config` 3 项、`backend_logs` 4 项、`backend_manager` 8 项、`backend_retry` 3 项、`backend_shutdown` 4 项、`managed_process` 2 项、`web_open` 2 项和 `workspace_file_open` 10 项；lib、main 与 doc-tests 没有用例。manager、retry、shutdown 和 managed-process 测试均通过。

共享 fixture `tests/fixtures/desktop_backend_config_cases.json` 共 34 条，其中 6 条期望成功、28 条期望拒绝。通过的 Rust 测试 `backend_config_matches_shared_contract_cases` 使用 `include_str!` 读取同一 fixture 并遍历所有案例；同一测试还断言拒绝错误不回显 `secret-value`。另两个配置测试验证 `{}` 默认端口 43127、默认 timeout、agent 字段忽略和 LaunchPlan 配置快照行为。

## 命令与日志

运行状态都保存了独立的 stdout、stderr 和 exitcode 文件；目录为 `C:\code\shikigen-agent\.scratch\desktop-network-refactor\validation\rust\`。

| cwd | 命令 | 退出码与结果 | 证据文件前缀 |
|---|---|---:|---|
| `frontend/src-tauri` | `cargo test --locked --test backend_config` | 101；Cargo 在测试启动前编译失败，0 项测试执行 | `cargo-backend-config` |
| `frontend/src-tauri` | `cargo test --locked --target-dir 'C:\code\shikigen-agent\.scratch\desktop-network-refactor\validation\rust\cargo-target' --test backend_config` | 0；3 passed | `cargo-backend-config-isolated` |
| `frontend/src-tauri` | `cargo test --locked --target-dir 'C:\code\shikigen-agent\.scratch\desktop-network-refactor\validation\rust\cargo-target'` | 0；36 passed | `cargo-full-isolated` |
| `frontend/src-tauri` | `rustfmt --check --edition 2021 --config skip_children=true src/backend.rs src/backend/manager.rs tests/backend_config.rs` | 0；通过 | `rustfmt-check` |
| `frontend` | `node --import tsx --test tests/tauri-command.test.mjs` | 0；9 passed | `node-tauri-command` |

首次 Cargo 专项尝试报告无法删除 `frontend/src-tauri/target/debug/shikigen-desktop.exe`（Windows `os error 5`），所以测试 harness 没有启动。只读进程查询观察到 PID 10548 正在运行该路径下的 `shikigen-desktop.exe`。没有等待用户关闭或停止该进程。初次 Cargo 尝试可能改写了原 `target` 中的其他构建缓存，因此本报告不声称原 target 整体未变化。

为保留该运行中 exe，之后使用 `robocopy C:\code\shikigen-agent\frontend\src-tauri\target C:\code\shikigen-agent\.scratch\desktop-network-refactor\validation\rust\cargo-target /E /XF shikigen-desktop.exe /R:0 /W:0 /NFL /NDL /NJH /NJS /NP` 复制缓存；robocopy 退出码为 1（复制了文件，属于 0–7 的成功状态），stderr 为空。目标路径解析确认位于仓库内，并确认隔离 target 中没有 `debug\shikigen-desktop.exe`。随后两条 Rust 测试命令都只使用隔离 target，原 exe 未触碰。

## 工具版本

| 工具 | 版本 |
|---|---|
| Cargo | `cargo 1.98.1 (797e8a9bc 2026-08-05)` |
| rustc | `rustc 1.98.1 (48a229cea 2026-09-01)` |
| rustfmt | `rustfmt 1.9.0-stable (48a229ceae 2026-09-01)` |
| Node | `v24.21.0` |

## 源码与 fixture SHA-256

以下 SHA-256 在验证开始前记录，并在隔离 Rust 回归结束后重新计算；四个受关注文件均一致。

| 文件 | 验证前 SHA-256 | 最终 SHA-256 | 一致 |
|---|---|---|---|
| `frontend/src-tauri/src/backend.rs` | `915FB3B75548F6EE2B2D4A89BA6B6B07E7454678F3EB5115E2CEA4311C193EFF` | `915FB3B75548F6EE2B2D4A89BA6B6B07E7454678F3EB5115E2CEA4311C193EFF` | 是 |
| `frontend/src-tauri/src/backend/manager.rs` | `A568EDEC2BA67F1F10D7C875E78BE0FD55D9E993CA91DC6612DFB320D1608665` | `A568EDEC2BA67F1F10D7C875E78BE0FD55D9E993CA91DC6612DFB320D1608665` | 是 |
| `frontend/src-tauri/tests/backend_config.rs` | `E352D0D405FD2514D7B6D2E063F49E7898CB25439122A5A897E8AA9BEF519D44` | `E352D0D405FD2514D7B6D2E063F49E7898CB25439122A5A897E8AA9BEF519D44` | 是 |
| `tests/fixtures/desktop_backend_config_cases.json` | `9222999F32DD648A6B0A3435122F5A64C23D1F8D7CFE7E43949FFE8F374BC3AC` | `9222999F32DD648A6B0A3435122F5A64C23D1F8D7CFE7E43949FFE8F374BC3AC` | 是 |

## 边界与未执行项

- 初次未隔离 target 的 Cargo 命令因 exe 访问拒绝而未进入测试阶段；之后两个隔离 target Cargo 命令均通过。初次 101 作为环境/构建阻塞记录，不计作测试失败。
- 本 agent 未运行 Python 测试。另一验证 agent 执行了 69 项受影响范围的 Python 回归（不是全仓 Python 套件）；其结果由主 agent 单独汇总。
- 没有启动付费模型、真实原生 GUI，也未复跑真实 Tauri CLI。本轮 Node 9 项通过注入的 CLI 回调与真实 Vite 验证监听端口及 CLI 参数/环境传递契约；未覆盖真实 WebView/HMR。
- 没有运行额外 Node 全量套件、Vite build 或 `cargo fmt`。

日志索引：`cargo-backend-config.*`、`cargo-backend-config-isolated.*`、`cargo-full-isolated.*`、`rustfmt-check.*`、`node-tauri-command.*`、`cargo-target-copy.*`、`sha256-before.csv`、`sha256-final.csv`、`sha256-final-comparison.txt`、`fixture-counts.txt`、`tool-versions.txt`、`desktop-process-observation.txt`、`executed-commands.txt`。


精确命令、工作目录、stdout/stderr 与 exit code 文件的逐项映射也保存在 `executed-commands.txt`。
