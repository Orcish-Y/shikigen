> 归档于 2026-10-07；正文状态与命令属于原开发阶段。当前完成情况见 [开发交接](../../../../development-handoff.md)。相对路径链接已迁移；代码块中的旧 scratch 路径需按归档路径调整。

# 会话列表页长调整：完成记录

日期：2026-10-04。主 agent 实现与修复；最终验证、两轴审查均委派 `gpt-6-luna / max`，独立上下文完整交接。主 agent 已核对原始输出与退出码。

## 实现

- HTTP：`GET /api/threads?limit=20`，下一页加 `cursor=...`。limit 必填正整数，无默认值；重复／未知参数与无效输入返回 422/no-store。
- Runtime → ChatStore → ThreadStore 必填传递 limit。store 预读 limit+1 条、返回最多 limit 条、据额外记录生成不透明游标；支持跨页改变 limit。
- 前端页长集中在 `frontend/src/conversation-state.ts` 的 `THREAD_PAGE_SIZE=20`，每条列表读取路径明确发送。同一配置用于末页与停滞判断，客户端按请求 limit 校验响应长度。
- 补修 SQLite 大整数绑定溢出：以十进制文本参数绑定，SQL CAST 处理数据库整数表示范围，保留调用方页长。实现依据见 [SQLite CAST 文档](https://www.sqlite.org/lang_expr.html#castexpr)；实际 HTTP／Python 边界证据见下。
- 规格、项目接口文档、当前实施票与正式测试调用已同步。第 3 票仍待实施。

## 验证结果

实际命令、工作目录、环境、复现与日志清单见 [后端报告](../../backend-history.zip)（包内：`docs/archive/2026-10-07/development/thread-page-limit/backend-report.md`） 和 [前端报告](../../backend-history.zip)（包内：`docs/archive/2026-10-07/development/thread-page-limit/frontend-report.md`）。

| 检查 | 实际结果与证据 |
| --- | --- |
| SQLite 补修前完整 Python 回归 | 289 方法：288 通过、1 跳过、0 失败，exit 0；[日志（原始产物已删除）](../../README.md#已删除的材料)、[退出码（原始产物已删除）](../../README.md#已删除的材料) |
| 补修后分页全文件 | 12/12，含大整数 HTTP + ChatStore 正式回归；[日志（原始产物已删除）](../../README.md#已删除的材料) |
| 补修后会话查询 / Server 集成 | 4/4 与 16/16，均 exit 0；[查询（原始产物已删除）](../../README.md#已删除的材料)、[Server（原始产物已删除）](../../README.md#已删除的材料) |
| 补修后极大 limit 探针 | 5 档均 HTTP 200/no-store，含 2^63−1、2^63、10^100；[日志（原始产物已删除）](../../README.md#已删除的材料) |
| 前端完整自动测试 | 30/30，0 失败／跳过，exit 0；[日志（原始产物已删除）](../../README.md#已删除的材料) |
| 前端读取路径参数探针 | 初读、刷新、重载、下一页、重试共 5 个列表请求均 limit=20；重试保留 cursor；[源码（原始产物已删除）](../../README.md#已删除的材料)、[输出（原始产物已删除）](../../README.md#已删除的材料) |
| Python 类型检查 | 生产范围 app / packages/harness 通过；[补修后日志（原始产物已删除）](../../README.md#已删除的材料) |
| 前端类型检查 / 构建 | 本地 tsc.cmd、pnpm.exe build 均 exit 0；[类型输出（原始产物已删除）](../../README.md#已删除的材料)、[构建输出（原始产物已删除）](../../README.md#已删除的材料) |
| Ruff | 13 个指定文件通过；最终补修两文件通过，[日志（原始产物已删除）](../../README.md#已删除的材料)。原生 pagination_acceptance.py 有 11 条既有诊断，前后快照相同，完整路径命令仍 exit 1，未计为通过 |

完整批次在 SQLite 补修前执行；补修后只运行受影响的 32 个专项方法及静态／极值检查，没有宣称最新代码执行了全仓 290 方法。前端没有受 SQLite 补修影响，复用已通过的 30 项、类型检查与构建。

唯一跳过项：`test_symlink_data_and_parent_are_rejected`，当前 Windows 环境无符号链接权限。

## 发现与修复

- 定向开发：可变页长 API 与客户端测试均先失败后通过；最终批量验证由轻量测试 agent 执行。
- 极值探针发现 limit+1 超出 SQLite INTEGER 时返回 500，主 agent 新增正式回归并修复。保留 [旧探针（原始产物已删除）](../../README.md#已删除的材料) 和 [正式红灯（原始产物已删除）](../../README.md#已删除的材料)；旧探针脚本不含失败断言，其 exit 0 仅表示脚本结束，不能当作极值通过。
- 前端初试 pnpm.cmd 因环境入口不可用而未启动；使用已有 tsc.cmd 和 pnpm.exe 验证。一次未保存 session 的早期 tsc 未计为通过；最终明确退出码均已归档。

## 审查

- **Standards：**标准硬违规 0、判断性 smell 0，含 SQLite 补修增量；[报告](../../backend-history.zip)（包内：`docs/archive/2026-10-07/development/thread-page-limit/standards-review.md`）。
- **Spec：**当前未修偏差 0、scope creep 0；原溢出问题已修复并由上述 32 个专项与极值探针补证；[报告](../../backend-history.zip)（包内：`docs/archive/2026-10-07/development/thread-page-limit/spec-review.md`）。

本次没有 UI/CSS 改动，未重新执行原生窗口、物理输入和多尺寸验收；这些范围仍归第 23 票。前端参数探针用公开客户端／store 与 fetch mock，后端使用真实 SQLite 与公开 HTTP；不把它们记为新的 Tauri 实机证据。
