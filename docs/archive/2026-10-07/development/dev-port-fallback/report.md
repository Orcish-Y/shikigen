> 归档于 2026-10-07；正文状态与命令属于原开发阶段。当前完成情况见 [开发交接](../../../../development-handoff.md)。相对路径链接已迁移；代码块中的旧 scratch 路径需按归档路径调整。

# 前端开发端口占用修复与验证

日期：2026-10-07。主 agent 负责实现；最终验证由三个 `gpt-6-luna / max` 子 agent 分别执行前端回归、真实 Tauri CLI 探测和 Python 后端回归。未执行 Git 操作。

## 使用方式与修复

在 `frontend` 目录继续运行 `pnpm tauri dev`。5173 被占用时，Vite 自动尝试后续端口；启动协调器保留实际监听，把实际 URL 作为本次 Tauri 配置，并将其 origin 传给托管 Python 后端的 CORS。无需结束占用端口的其他程序，也无需手工编辑端口。

- [启动协调器](../../../../../frontend/scripts/tauri-command.mjs)与[入口](../../../../../frontend/scripts/tauri.mjs)：先监听，再调用真实 CLI，覆盖 `devUrl`，关闭重复的 `beforeDevCommand`，结束时恢复环境并关闭监听。
- [package.json](../../../../../frontend/package.json)、[Vite 配置](../../../../../frontend/vite.config.ts)、[Tauri 配置](../../../../../frontend/src-tauri/tauri.conf.json)：普通开发命令自动回退；非开发命令原样转交。直接调用 `pnpm exec tauri dev` 或 `cargo tauri dev` 绕过协调器，仍使用固定端口并在占用时明确报错。
- [桌面后端](../../../../../app/desktop.py)：CORS 使用本次实际 origin 和既有 Tauri origin，验证传入的 HTTP(S) origin，不扩大为任意端口或通配来源。
- [启动测试](../../../../../frontend/tests/tauri-command.test.mjs)、[后端测试](../../../../../tests/test_desktop.py)与[使用说明](../../../../../frontend/README.md)：补充端口占用、参数传递、环境恢复、失败清理和真实请求验证。

修复前已通过自有 HTTP 监听复现原配置 `strictPort=true` 的占用错误；最终真实 CLI 探测在自有监听占用 5173 与 5174 时选择 5175，原监听持续返回 200。

## 最终验证结果

| 范围 | 结果 | 证据 |
| --- | --- | --- |
| 前端启动专项 | 9/9 通过，退出码 0 | [前端最终报告](../../backend-history.zip)（包内：`docs/archive/2026-10-07/development/dev-port-fallback/validation/static/cors-final/summary.md`） |
| 完整 Node 回归 | 278/278 通过，失败、跳过均为 0，退出码 0 | [原始回归日志（原始产物已删除）](../../README.md#已删除的材料) |
| 前端构建 | `pnpm build` 退出码 0；含 TypeScript 检查及 Vite 构建 | [构建日志（原始产物已删除）](../../README.md#已删除的材料) |
| 两个启动脚本语法检查 | 均退出码 0 | [前端最终报告](../../backend-history.zip)（包内：`docs/archive/2026-10-07/development/dev-port-fallback/validation/static/cors-final/summary.md`） |
| 真实 Tauri CLI | 实际 origin 与 devUrl 一致，页面及 `/@vite/client` 返回 200；runner 错误 23 与非法参数错误 2 按预期传播并释放端口 | [最终 CLI 报告](../../backend-history.zip)（包内：`docs/archive/2026-10-07/development/dev-port-fallback/validation/cors-final/report.md`）、[命令及哈希记录（原始产物已删除）](../../README.md#已删除的材料) |
| Python 桌面专项 | 16/16 通过，失败、跳过均为 0，退出码 0 | [专项日志（原始产物已删除）](../../README.md#已删除的材料) |
| 完整 Python 回归 | 338 项中 336 通过、1 个测试出错、1 项跳过，退出码 1；完整回归未通过 | [后端报告](validation/backend/report.md)、[原始日志](../../unresolved-issues-evidence.zip)（包内：`docs/archive/2026-10-07/development/dev-port-fallback/validation/backend/python-full.log`） |
| Ruff、格式检查、ty | 指定范围全部通过，退出码 0 | [后端命令与结果](validation/backend/report.md) |

Python 专项实际验证了选中 origin 的预检、会话查询、消息发送、SSE 完成、生产 Tauri origin，以及拒绝其他端口来源。源码哈希在验证前后保持一致；主 agent 已核对报告、原始日志、CLI runner 捕获及最终源码哈希。

## 未通过项与范围限制

完整 Python 回归的独立出错项为 `test_waits_for_previous_cleanup_and_survives_caller_cancellation`，在原有 3 秒等待处超时，并连带触发临时数据库文件清理错误；两条异常记录属于同一个测试。原样单项运行两次同样超时。仅增加计时的诊断显示第二轮 Graph 耗时 2.668 秒，随后数据库结算超出剩余等待预算并在收尾时被取消。该诊断未加载 `app.desktop`，没有经过本次 CORS 改动路径；这些结果没有证明恢复算法存在缺陷，也没有证明该用例已恢复稳定。未修改超时或断言以获得通过。详见[诊断日志](../../unresolved-issues-evidence.zip)（包内：`docs/archive/2026-10-07/development/dev-port-fallback/validation/backend/approval-timing.log`）。

跳过项为 Windows 符号链接权限检查，原因是当前环境无符号链接创建权限。实际 WebView 页面刷新、HMR 和 Cargo 应用构建未执行；CLI 探测使用真实 Tauri CLI 与隔离 capture runner，Python 接口验证使用独立临时后端。未调用付费模型或供应商。早期 Ctrl-C 清理证据位于[早期 CLI 报告](../../backend-history.zip)（包内：`docs/archive/2026-10-07/development/dev-port-fallback/validation/native/report.md`），早于新增 origin 环境传递，不作为该变量恢复的实机证据。

前端构建发生在最后的 MJS/Python CORS 补充之前；之后未修改 TypeScript、UI 或 Rust 构建输入，最终 MJS 已完成语法检查与 Node 回归。构建保留既有单个 JS chunk 大于 500 kB 的提示。

开发阶段曾出现短生命周期 Vite 测试 fixture 在 watcher 初始化期间关闭导致 Node 不退出，以及一次针对规范化配置形状的测试断言失败。这些过程结果保留在[前端验证目录](../../backend-history.zip)（包内：`docs/archive/2026-10-07/development/dev-port-fallback/validation/static/*`），没有计入最终通过数量。fixture 仅忽略文件监听，仍保留实际绑定、HTTP 响应、占用服务存活和退出后重新绑定等断言；产品开发服务器继续启用文件监听。临时计时观测仅位于本验证目录。
