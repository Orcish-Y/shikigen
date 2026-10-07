> 归档于 2026-10-07；正文状态与命令属于原开发阶段。当前完成情况见 [开发交接](../development-handoff.md)。相对路径链接已迁移；代码块中的旧 scratch 路径需按归档路径调整。

# 审批恢复用例等待结算超时

Status: needs-triage

发现日期：2026-10-05。来源：首版前端实施第 04 票的后端完整回归。

## 问题与影响

`ApprovalResumeTests.test_waits_for_previous_cleanup_and_survives_caller_cancellation` 在 `tests/test_approval_resume.py:258` 的 `await asyncio.wait_for(settled.wait(), 3)` 超时。完整后端回归共 291 项：289 通过、1 跳过、1 错误；原正式用例隔离复测两次均在相同位置失败，不能把完整回归记为通过。

本次前端第 04 票未修改审批恢复产品路径或该正式用例；新增的后端测试仅验证发送原文和既有 surrogate 替换，并已通过。尚未确认超时根因，也没有证明它与本轮改动完全无关。

## 精确复现

工作目录：`C:/code/shikigen-agent`；Python 3.12、Windows、仓库现有 `.venv`。

```powershell
.venv/Scripts/python.exe -X utf8 -m unittest discover -s tests -p test_approval_resume.py -k test_waits_for_previous_cleanup_and_survives_caller_cancellation -v
```

最终验证执行模型：`gpt-6-luna / max`。完整回归运行 636.388 秒；两次正式隔离复现分别运行 6.169 秒和 6.017 秒。Windows symlink 权限导致的另一项跳过与本错误分别记录。

## 已有诊断证据

- scratch 探针运行两次均到达结算事件；它增加观测后改变了执行时序，不能代替正式用例或抵消其失败。
- 最近一次探针中 `transitions is coordinator._settlement` 为真，原始 `settle_execution` 未抛异常；相对 resume 起点在 2.828 秒进入、3.297 秒返回并触发事件。该累计时间包含进入等待前的工作，不代表正式用例的 3 秒计时也通过。
- 触发时持久 Run 为 `interrupted`，registry 保留 second；后台任务停在探针的 `release.wait()`，释放后正常结束且 `exception=None`。
- 可能存在等待链问题、结算异常或对执行耗时敏感的测试窗口。现有探针倾向最后一种，但正式用例的失败时间线尚未完整捕获，根因仍待定位。

## 后续调查与完成条件

- 保持正式用例的断言和超时，捕获失败运行中等待开始、前次 cleanup 完成、恢复任务创建和结算事件的单调时钟时间线及任务栈。
- 区分实际生命周期／取消传播缺陷和测试调度依赖；若需修改测试，证明它仍验证前次清理互斥与调用方取消后的结算行为。
- 修复由主 agent 实施，再由轻量模型验证正式用例、相关审批／运行回归及必要完整回归。不得只依赖 scratch 探针通过，也不得通过放宽时限掩盖问题。

## 证据

- [后端最终报告](../archive/2026-10-07/frontend-history.zip)（包内：`docs/archive/2026-10-07/development/frontend-completion/ticket-04/backend-report.md`）
- [完整回归日志](../archive/2026-10-07/unresolved-issues-evidence.zip)（包内：`docs/archive/2026-10-07/development/frontend-completion/ticket-04/backend-full-suite.log`）
- [正式隔离复现一](../archive/2026-10-07/unresolved-issues-evidence.zip)（包内：`docs/archive/2026-10-07/development/frontend-completion/ticket-04/backend-approval-resume-repro.log`）
- [正式隔离复现二](../archive/2026-10-07/unresolved-issues-evidence.zip)（包内：`docs/archive/2026-10-07/development/frontend-completion/ticket-04/backend-approval-resume-confirmation.log`）
- [探针日志](../archive/2026-10-07/unresolved-issues-evidence.zip)（包内：`docs/archive/2026-10-07/development/frontend-completion/ticket-04/backend-approval-resume-diagnostic.log`）和[诊断脚本](../archive/2026-10-07/unresolved-issues-evidence.zip)（包内：`docs/archive/2026-10-07/development/frontend-completion/ticket-04/diagnose_approval_resume.py`）

## 后续复核

2026-10-05 前端第 05 票最终后端回归由 `gpt-6-luna / max` 单次执行完整正式套件：291 项、290 通过、1 Windows symlink 环境跳过、无失败或错误（358.668 秒，exit 0），本用例标记 `ok`。本轮未改审批产品或该测试，也未确认历史超时根因；保留 `needs-triage`，不将单次未复现等同于修复。证据见[第 05 票后端报告](../archive/2026-10-07/frontend-history.zip)（包内：`docs/archive/2026-10-07/development/frontend-completion/ticket-05/backend-report.md`）及[完整日志（原始产物已删除）](../archive/2026-10-07/README.md#已删除的材料)。

2026-10-05 前端第 06 票完整正式后端回归仍由显式调度 `gpt-6-luna / max` 单次执行：291 项、290 通过、1 Windows symlink 环境跳过、无失败或错误（340.563 秒，exit 0），同一本用例再次 `ok`。未修改审批产品路径、该正式测试或其3秒时限，未补根因调查；仍保留 `needs-triage`。证据见[第 06 票后端报告](../archive/2026-10-07/frontend-history.zip)（包内：`docs/archive/2026-10-07/development/frontend-completion/ticket-06/backend-report.md`）和[完整日志（原始产物已删除）](../archive/2026-10-07/README.md#已删除的材料)。

2026-10-05 第 07 票完整正式后端回归中，本用例仍为 `ok`；本轮整体为 291 项、289 通过、1 错误、1 Windows symlink 权限跳过（384.388 秒，exit 1）。唯一错误是另一个桌面环境配置用例的退出等待超时，见[独立问题](empty-host-environment-startup-exit.md)。未修改审批路径、正式用例或时限，也未确认历史根因；本问题保持 `needs-triage`，不将连续未复现当作修复。证据见[第 07 票后端报告](../archive/2026-10-07/frontend-history.zip)（包内：`docs/archive/2026-10-07/development/frontend-completion/ticket-07/backend-report.md`）和[完整日志](../archive/2026-10-07/unresolved-issues-evidence.zip)（包内：`docs/archive/2026-10-07/development/frontend-completion/ticket-07/backend-unittest.log`）。

2026-10-05 第 10 票再次复现同一正式用例、同一第 258 行的 3 秒等待超时。该批完整回归为 301 项：299 通过、1 错误、1 Windows symlink 环境跳过（721.361 秒，exit 1），见[原始完整日志](../archive/2026-10-07/unresolved-issues-evidence.zip)（包内：`docs/archive/2026-10-07/development/frontend-completion/ticket-10/backend/full-unittest-final5.log`）。本票修改了 Run 的预览接入与结算互斥路径；只读锁顺序检查未发现明确的新死锁环，但尚未确认失败根因，不能断言与本票变更无关，也不能仅归因于当时与原生验收并行。

第 10 票最终 23 项原生验收结束后，由 `gpt-6-luna / max` 保持原正式命令、断言和 3 秒时限串行隔离两次：第一次 1 项通过（12.430 秒，exit 0）；第二次 1 项错误（6.557 秒，exit 1），仍在第 258 行 TimeoutError。见[隔离一（原始产物已删除）](../archive/2026-10-07/README.md#已删除的材料)、[隔离二](../archive/2026-10-07/unresolved-issues-evidence.zip)（包内：`docs/archive/2026-10-07/development/frontend-completion/ticket-10/backend/approval-timeout-isolated-2.log`）与[第 10 票后端报告](../archive/2026-10-07/frontend-history.zip)（包内：`docs/archive/2026-10-07/development/frontend-completion/ticket-10/backend/backend-report.md`）。第一次通过不能抵消第二次失败；继续保留 `needs-triage`，最终另做一次串行全套，结果单独记录，不反复重跑直到通过。

第 10 票最后单次无原生并行的完整回归为 301 项：300 通过、0 失败／错误、1 Windows symlink 环境跳过（359.477 秒，exit 0，UTC 12:55:43.315–13:01:53.553）；本用例为 ok。见[最终串行日志（原始产物已删除）](../archive/2026-10-07/README.md#已删除的材料)。没有修改本用例或确认根因，前述完整失败和隔离二错误仍有效，问题状态不变。


## 2026-10-07 整理补记

端口回退完整后端回归再次出现原 3 秒等待超时：338 项中 336 通过、1 错误、1 权限跳过；原正式隔离两次也超时。计时诊断显示第二轮 Graph 耗时约 2.668 秒，后续结算超过剩余预算，但尚未证明根因或修复。详见 [当轮报告](../archive/2026-10-07/development/dev-port-fallback/validation/backend/report.md)。后续网络模块相关测试通过没有覆盖或关闭本问题。
