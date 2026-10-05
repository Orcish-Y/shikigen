# 断流后的有限 GET 恢复与手动重连

Status: done

实施进度：已验收

来源：[统一实施规格](../../../../.scratch/frontend-completion/PRD.md)；[公共要求与依赖总览](index.md)。

**What to build:** 意外断流后自动有限次数恢复同一运行，停止后保留手动重连和状态查询，正常等待审批或终态结束保持真实结果。

**Why:** 把观察故障与执行结果分开，提供可预测且不会重复执行的恢复路径。

**API／边界：**同 Run GET stream／纯读查询；结构化 HTTP 与 SSE error；统一读取任务、计时和 Retry-After。

**Blocked by:** [全量重建消息与当前运行事实](03-run-fact-reconstruction.md)。

## 验收条件

- [x] 分别显示未建立、连接中、已建立、重试等待、正常结束、暂停和恢复停止；running 意外 EOF 可恢复，interrupted／终态正常 EOF 不重连，不将连接错误写成 Run error。
- [x] 网络、GET 503／可恢复 SSE error 按 1／2／5 秒最多三次 GET；不早于 Retry-After，同一故障的 error 与 EOF 不重复安排，同目标无并发连接。
- [x] 首帧 metadata 不重置失败计数，连续正常 30 秒或正常 interrupted／终态 回放完成才重置；三次失败后保留事实和手动入口，列表轮询不不断重开恢复。
- [x] 手动重连、重新进入／显示和有效新租约可开启新轮次，复用任务并遵守等待；主动 Abort／失效不消耗次数或取消后台任务。
- [x] 404、GET stream 400、GET 500、不可恢复 SSE error／解析失败停止自动恢复并提供对应手动路径；长工具无输出不按超时判失败。
- [x] POST 错误只核实，不自动重发；保留 status／detail／Retry-After、SSE code／message／recoverable，未分类错误保留说明，不自动重启宿主。
- [x] 以可控公开网络边界验证次数／间隔、Retry-After、metadata 后即失败、重复 EOF、失效计时器及手动竞争，并在工作台演示断流恢复。

## Comments

2026-10-05：用户授权完成第 5 票并要求延迟 30 分钟开始，已于北京时间 02:30 开始。验证沿用规格定稿的公开 HTTP／SSE 网络边界、BackendSession／ConversationStore 公开入口和既有 Tauri 实机夹具。主 agent 实施，最终验证由 `gpt-6-luna / max` 子 agent 执行；不执行 Git 写操作。窗口显隐桥接和周期性轮询归第 6 票。

2026-10-05 验收：有限 GET 恢复、手动重连／纯状态查询、结构化错误与中文状态已接入工作台，已接受发送断流时补读真实原文，草稿和事实保留。最新前端全套 **93／93**、TypeScript、构建、原生脚本 ruff 通过；真实 Tauri 本票 **2／2**、第 04 票回归 **4／4**、第 03 票回归 **3／3** 通过。后端完整套件 **291 项：290 通过、1 Windows symlink 权限跳过、0 失败／错误**，专项及 ty 通过。Spec／Standards 审查发现的空 SSE 无 metadata 误重试及 aria-live 秒级播报已修复并复核，无未解决硬缺口。

主已核对实际日志、构建资源、公开 history／snapshot／请求时序及工作台截图。票据中的重新显示恢复入口将在第 06 票接入实际显隐桥接；本轮已验证手动、重新选择、有效新租约和 Abort 生命周期。Windows 当前锁屏，实机业务在真实 Tauri WebView 中验证，退出清理走核实菜单身份的原生菜单命令；物理键鼠、系统 IME、窗口边框与多尺寸联合验收留第 23 票，未计作已通过。此前审批清理超时本轮未复现，根因仍待调查。完整证据及边界见[实施与验收报告](../../../../.scratch/frontend-completion/ticket-05/report.md)。
