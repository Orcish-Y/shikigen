> 归档于 2026-10-07；正文状态与命令属于原开发阶段。当前完成情况见 [开发交接](../development-handoff.md)。相对路径链接已迁移；代码块中的旧 scratch 路径需按归档路径调整。

# 空宿主环境变量启动错误：完整回归等待退出超时

Status: needs-triage

发现日期：2026-10-05，第 07 票最终后端回归。该票没有修改后端产品或本用例。

## What / Why / How

- **What**：确认空字符串宿主环境变量导致配置校验失败时，桌面进程能自行退出；排查完整回归中出现的 20 秒退出等待超时。
- **Why**：首轮完整测试出现真实错误，隔离通过不能证明根因已经解决。
- **How**：沿用正式进程与配置测试 `DesktopTests.test_environment_loaded_before_config_without_overriding_host`，通过子进程退出及公开启动错误结果核对，不改等待时限或配置语义。

## 原始失败

根目录命令：`.venv/Scripts/python.exe -X utf8 -m unittest discover -s tests -v`。

正式结果：291 项，289 通过、1 错误、1 跳过；`FAILED (errors=1, skipped=1)`，exit 1。用例在 [test_desktop.py](../../tests/test_desktop.py#L225) 的 `await asyncio.wait_for(process.wait(), 20)` 抛出 TimeoutError；对应循环 `value == ""` 分支。

原始日志：[第 07 票完整后端回归](../archive/2026-10-07/unresolved-issues-evidence.zip)（包内：`docs/archive/2026-10-07/development/frontend-completion/ticket-07/backend-unittest.log`）。跳过项是 Windows symlink 权限，不属于本错误。

## 核实与现状

正式原用例隔离复测两次，各 1 项通过；每次覆盖 `None`、空字符串与 `host-model` 三个分支。未修改产品代码、用例、超时或断言。证据：[首轮隔离日志](../archive/2026-10-07/unresolved-issues-evidence.zip)（包内：`docs/archive/2026-10-07/development/frontend-completion/ticket-07/backend-isolated-environment-test.log`）、[第二轮隔离日志（原始产物已删除）](../archive/2026-10-07/README.md#已删除的材料)。

失败未在首轮隔离中复现，根因未确认；没有证据将其归因于资源争用或某个产品分支。后续诊断应先建立可稳定重现的最小回路，保留 stdout／stderr 和进程退出证据，核实究竟是启动、退出还是管道读取等待。

## Comments

本问题独立追踪。第 07 票正文／网页打开验收与完整仓库回归分别记录；不能把隔离通过改算成首轮完整回归通过。
