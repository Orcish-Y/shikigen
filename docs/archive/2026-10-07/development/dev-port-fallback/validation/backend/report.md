> 归档于 2026-10-07；正文状态与命令属于原开发阶段。当前完成情况见 [开发交接](../../../../../../development-handoff.md)。相对路径链接已迁移；代码块中的旧 scratch 路径需按归档路径调整。

# 后端验证报告：dev port fallback

- 执行模型：gpt-6-luna，推理强度 max
- 工作目录：`C:\code\shikigen-agent`
- 验证日期：2026-10-07
- 职责范围：Python 后端 CORS origin 选择与回归验证；未修改产品源码、测试断言或 Rust 代码。
- 所有命令输出保存在本目录；首次完整回归日志单独保留，后续单项复现未覆盖它。

## 结果

| 验证 | 命令 | 结果 | 日志 |
|---|---|---|---|
| 桌面后端专项 | `.venv/Scripts/python.exe -X utf8 -m unittest discover -s tests -p test_desktop.py -v` | exit 0；16 passed，0 failed，0 skipped；155.499s | `python-desktop.log` |
| 全量 Python 回归（首次结果） | `.venv/Scripts/python.exe -X utf8 -m unittest discover -s tests -v` | exit 1；Ran 338 in 821.420s：336 passed，1 个独立测试出错（unittest 记有 2 条 error），1 skipped | `python-full.log` |
| 审批恢复单项复现 1 | `.venv/Scripts/python.exe -X utf8 -m unittest discover -s tests -p test_approval_resume.py -k waits_for_previous_cleanup_and_survives_caller_cancellation -v` | exit 1；1 error，6.937s | `approval-cleanup-repro-1.log` |
| 审批恢复单项复现 2 | 同上 | exit 1；1 error，6.702s | `approval-cleanup-repro-2.log` |
| 计时诊断 runner | `.venv/Scripts/python.exe -X utf8 .scratch/dev-port-fallback/validation/backend/approval_timing_probe.py` | exit 1；原测试仍以 3 秒等待超时，1 error；仅观测计时，不替代测试结果 | `approval-timing.log` |
| Ruff lint（本次文件） | `.venv/Scripts/ruff.exe check app/desktop.py tests/test_desktop.py` | exit 0；All checks passed | `ruff-check.log` |
| Ruff format（本次文件） | `.venv/Scripts/ruff.exe format --check app/desktop.py tests/test_desktop.py` | exit 0；2 files already formatted | `ruff-format-check.log` |
| ty（指定目录） | `.venv/Scripts/ty.exe check app packages/harness/shikigen` | exit 0；All checks passed | `ty-check.log` |

全量回归唯一的跳过项是 `test_runtime_data.RuntimeDataTests.test_symlink_data_and_parent_are_rejected`，原因是 `Windows symlink privilege is unavailable`。两条 error 记录属于同一个审批恢复用例：原用例超时，以及其后的临时目录清理遇到文件占用；不是两个独立测试失败。

## 失败证据与计时

全量回归中，`test_approval_resume.ApprovalResumeTests.test_waits_for_previous_cleanup_and_survives_caller_cancellation` 在 `tests/test_approval_resume.py:258` 等待 `settled.wait()` 的 3 秒 deadline 超时。随后 Windows `TemporaryDirectory` 清理 `product.db` 时收到 WinError 32（文件仍被另一个程序占用），产生第二条 cleanup error。两次原样单项复现都在相同的 `settled.wait()` 位置以 TimeoutError 失败。

计时 runner 观察到：

- `app.desktop` 在测试导入前后都未加载。
- 第一轮 graph 用时 1.161s，settlement 用时 0.561s，均完成。
- 第二轮 graph 用时 2.668s；随后 settlement 开始，并在约 0.459s 后因测试取消而收到 `CancelledError`。
- 这次观测与 graph 执行和后续 settlement 合计超过用例 3 秒等待窗口相符。它不能证明恢复算法存在缺陷，也不能证明该用例稳定失败；该诊断没有改变产品代码或测试超时/断言。

复现日志与 timing runner 日志分别保留，不以单项/诊断结果替换首次全量结果。按主 agent 指示，连续两次单项失败后停止追加该测试及整类复跑。

## 源码哈希

验证开始时主 agent 已完成格式整理；我在专项测试前和验证结束后核对 `app/desktop.py` 与 `tests/test_desktop.py` 的 SHA-256，前后相同：

- `app/desktop.py`: `1C743A50287F354DC02FC0D9DAF7002C47C6F60D27B8357B87652A721E7EF9FD`
- `tests/test_desktop.py`: `C91712DDDAC6444443B69FDA3C3D8D74B733D8CFA16356D4C45CA483BD3460C1`

哈希快照：`sourcehash-before.txt`、`sourcehash-after.txt`。

## 覆盖边界

这份报告只覆盖 Python 后端、`app/desktop.py` 与 `tests/test_desktop.py` 的 Ruff 检查，以及 `app` 和 `packages/harness/shikigen` 的 ty 检查。没有运行付费模型/供应商调用、GUI 实机测试或 Rust 检查；这些不在本次后端验证范围内。Windows 符号链接权限缺失使对应测试跳过。
