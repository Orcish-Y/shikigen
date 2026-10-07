> 归档于 2026-10-07；正文状态与命令属于原开发阶段。当前完成情况见 [开发交接](../../../../development-handoff.md)。相对路径链接已迁移；代码块中的旧 scratch 路径需按归档路径调整。

# 统一消息写入与运行结算事务

完成日期：2026-10-06（Asia/Shanghai）。

## 目标与实现

用户授权移除 `partial_messages`，让取消、失败和正常消息复用持久化入口；保留原有正文保存、运行恢复和终态竞争的行为。本轮已重新读取 AGENTS.md，主 agent 负责实现和修复，最终验证交给显式 `gpt-6-luna / max` 子 agent。

| 层 | 当前责任 | API |
| --- | --- | --- |
| RunEventIngestor | 缓存预览；将未提交正文组装为规范 AI 消息；持接入锁协调共享事务 | `settle`、`cancel`、`_write_buffered_messages` |
| EventStore | 规范化、消息身份、metadata、幂等、冲突、预留 seq 与实际写入 | `write_message_in_transaction` |
| RunTransitions | 状态、用量、审批和生命周期事实；不接收消息正文 | `settle_execution_in_transaction`、`cancel_run_in_transaction` |
| RunExecutionCoordinator | 绑定事务内状态方法；负责提交后发布、失败结算重试与执行清理 | `_settle_outcome`、`cancel` |

`settle_execution` 和 `cancel_run` 保留为独立事务包装入口；已有无 ingestor 的调用路径仍可用。普通自动提交消息和创建 Run 的用户入口消息也使用相同消息 writer。产品源码已移除 `partial_messages`。

### 保存顺序

1. Graph 的流式片段仍只缓存正文并推送预览。
2. Run 接入锁冻结缓冲，开启一个 `ChatStore.transaction`。
3. 失败仅在 Run 仍 running 时保存缓冲；取消仅在 Run 尚非终态时保存。已经提交的完整／中止消息保留原事实。
4. 按原 message_id、预留 seq 与片段顺序组装普通 AI 消息，`generation_status` 为 `error` 或 `cancelled`；不裁剪正文，不制造部分工具调用。
5. 先实际写入这些消息，再由事务内状态方法结算 Run、用量和生命周期。后续 invocation／approval／usage 校验失败时，消息与状态一起回滚。
6. 数据库提交成功后才清空缓存、封口和广播。广播顺序为消息在前、终态在后；id 游标保持单调。

回滚仍保留正文和原失败 outcome；原 owner 只重试事务，不重新执行 Graph。取消写失败时不请求 abort。首个有效终态、晚到用量、interrupted 以及根快照重放保护沿用已有规则。

## 文件范围

产品仅修改四个 Python 文件：

- `packages/harness/shikigen/persistence/event_store.py`
- `packages/harness/shikigen/runtime/run_events.py`
- `packages/harness/shikigen/runtime/run_execution.py`
- `packages/harness/shikigen/runtime/runs.py`

新增 `tests/test_message_write_transaction.py` 的 7 项共享事务验证；调整八个旧测试文件的故障注入、提交前后 barrier 和协议 fake，不删除或放宽原断言。同步修正对象与回调命名，如 `committed_message_ids`、`settlement`、`write_result`、`running_event`、`settle_fn`、`cancel_fn`。

数据库 schema、HTTP/SSE、前端与依赖没有改动。本轮仅内部重构；不推进下一实施票据。

## 验证记录

运行验证与独立静态审阅均使用 `gpt-6-luna / max`，工作目录 `C:/code/shikigen-agent`。完整交接见 [validation-context.md](../../backend-history.zip)（包内：`docs/archive/2026-10-07/development/message-write-refactor/validation-context.md`）。命令、时间、退出码与原始日志在 [logs/（原始产物已删除）](../../README.md#已删除的材料)；详细结果分别由子 agent 写入运行和静态报告。专项与完整回归有重叠，不能相加声称独立测试数量。

- [运行验证报告](../../backend-history.zip)（包内：`docs/archive/2026-10-07/development/message-write-refactor/runtime-report.md`）
- [独立静态检查与代码审阅报告](../../backend-history.zip)（包内：`docs/archive/2026-10-07/development/message-write-refactor/static-report.md`）

12 个专项文件的最终结果为 126 项通过、0 失败、0 错误、0 跳过。原 Runtime 首错保留；修复后 20 项另存 `test_runtime-r2`。

唯一一次完整后端回归已完成：**320 项，319 通过、0 失败、0 错误、1 跳过，退出码 0**。主 agent 已核对完整日志尾部、元数据与跳过记录；新增 7 项包含在这 320 项中。实际命令：

```powershell
.venv/Scripts/python.exe -X utf8 -m unittest discover -s tests -v
```

日志统计耗时 528.496 秒；元数据记录 UTC 2026-10-05 17:12:11 至 17:21:08。唯一跳过是 `test_runtime_data.RuntimeDataTests.test_symlink_data_and_parent_are_rejected`，原因为 `Windows symlink privilege is unavailable`，没有计为通过。完整证据：[原始日志（原始产物已删除）](../../README.md#已删除的材料)、[命令／退出码／统计（原始产物已删除）](../../README.md#已删除的材料)。

产品代码 `ty check app packages/harness`、新增事务测试单独 ty、13 文件 Ruff check／format 在 r2 均退出 0。审阅提出的最后一处对象命名已修正，产品 ty 与 `runs.py` Ruff check／format 的 r3 也退出 0。

独立审阅未发现剩余硬问题；验证过事务所有权、锁顺序、消息身份与 seq、首终态、缓冲回滚、提交后发布时序及原测试断言保留。

旧测试合并 ty r2 仍有 152 项诊断；与修改前快照 diff 的行范围对照后，诊断均落在既有测试行，不在本轮新增／修改行。该对照未在完整修改前包上重新执行 ty，不能单凭行位置证明全部诊断修改前就存在。未通过的旧测试类型检查如实保留，未添加忽略规则或降低检查标准；本轮产品代码和新增测试的独立检查无诊断。

### 已发现并修复的问题

- 首轮 Runtime 测试仍拦截 RunEventIngestor 的第二次写入；用户入口消息迁移到统一 writer 后，故障注入没有发生。首错记录为 1 失败、2 错误。主 agent 改为在统一 writer 实际写入用户消息后注入 OSError／CancelledError；保留 Run 与所有消息回滚的原断言。原始失败日志保留，修后另存 r2。
- 首轮静态检查发现 callback union 类型、一个 append 闭包错误转发 args、新 get_run 结果与 ingestor 的可空访问、新测试 import 排序。主 agent 已修正，产品和新测试 r2 检查通过。
- 首轮九个相关测试文件 ty 合并检查报 159 项，修后为 152 项旧测试代码诊断。不能将这次合并检查说成通过；本轮新诊断修复、旧测试问题与基线核对限制由静态报告分别说明。

## 工作区与验证范围

主 agent 和验证子 agent 没有执行 staging、reset 或 commit。暂存内容使用 `git ls-files --stage` 的 path／blob／stage 清单只读核对：r2 两边 2412 条、差异 0；后续当前清单变为 2457 条，出现 45 个本轮证据条目和 5 个测试文件 staged blob 更新，来源未确定。详见 [staged-manifest-delta-final.json（原始产物已删除）](../../README.md#已删除的材料)。没有复原、覆盖或调整暂存内容。`.git/index` 二进制 hash 的变化本身不能直接等同于暂存内容改变。

本轮不执行 Tauri 实机／物理系统 IME 检查，没有将未执行项算作通过。此前审批 cleanup 超时、Windows 空环境宿主退出超时、IME Enter 偶发失败继续按原 needs-triage 记录保留；本轮回归通过不能抵消历史失败。

持续写失败仍只持有进程内 owner；强杀进程时未提交内存不保证恢复。GET 仍为读取，不补写。失败结算的异常分类和重试策略没有在这次重构中扩大范围。
