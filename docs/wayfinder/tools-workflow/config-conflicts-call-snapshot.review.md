# 13 号票审查与验收记录

规格：[保存结果、外部修改与调用生效规则](config-conflicts-call-snapshot.md)，原票 `.scratch/tools-workflow/issues/13-config-conflicts-call-snapshot.md`。开发基点 `0266fb59d135a1489979aff5f02dcc28644b6f94`。

2026-10-23 后续用户决定取消清理 warnings，改由后端在后续配置提交或启动时重试。以下初次审查与验收保留为历史记录，涉及旧警告响应和旧原生方法名的内容不代表当前契约；本轮调整及验证追加在文末。

按 implement／TDD 技能沿用公开 API、真实临时文件和页面交互边界，源码版本、Windows 提交后清理警告、OpenAPI 批次版本和外部提交后引用保护分别先观察失败再实现。没有通过私有方法调用次数断言结果。

## Standards

code-review 技能的独立标准审查检查暂存差异 `git diff --cached 0266fb59d135a1489979aff5f02dcc28644b6f94 --`。依据包括 `frontend/design.md`、工具 HTML 原型、002／003／004 决议及最新 HTTP 认证记录；未找到 AGENTS、CLAUDE、CONTRIBUTING 或 CODING_STANDARDS 文件。

初审 1 项 P2：脏连接被外部删除后，明确放弃仍请求已删除的详情，无法恢复本地目录。违反前端设计中的明确放弃后重读规则。修复为先重读连接列表，目标存在才读详情，目标不存在则清除已明确放弃的草稿并恢复目录；读取失败继续保留草稿。独立复核确认解决，未发现新增标准问题。

## Spec

独立规格审查初审 2 项 P2，分别对应票据的外部修改与重读恢复要求：

1. 新建连接草稿没有实际读取版本，普通刷新也误判冲突，且缺少新草稿恢复入口。
2. 已有连接被外部删除后的恢复问题，与标准审查单独记录的同一问题相符。

修复为保存连接列表版本、新建时使用该版本，并为新草稿和已有连接提供先重读列表的明确放弃入口。新增公开 DOM 回归先失败后通过，完整 MCP 页面文件 10 项通过。独立复核确认两项均已解决，未发现新的规格问题。

两条审查线最终均无遗留发现；初审分别为 Standards 1 项、Spec 2 项，均已处理，没有合并两条审查线的计数。

收尾补充检查发现 `glob` 会静默跳过目录枚举错误，改用显式 `iterdir`，仅目录不存在视为无待清理文件。文件系统边界回归先观察到错误的 204，再验证已提交的 200／warnings 及实际新源码执行；Spec 独立复核确认符合要求且无新增发现。

## 验证记录

日志与截图位于忽略目录 `.scratch/tools-workflow/`，不作为产品构建内容提交。

- 后端全量 `python -m unittest discover -s tests -q` 运行 465 项，464 项通过、1 项跳过，604.849 秒（`13-backend-full.log`）。此后目录枚举边界修复由下述 12 项专项回归验证。
- 新增 API／文件生命周期文件最终 12 项测试全部通过（10.566 秒，`13-config-api-final.log`）。真实 stdio MCP、HTTP 和 Python 调用确认当前调用固定使用旧内容，下一次读取新内容；真实 Windows 文件占用覆盖配置替换失败和提交后清理失败。全量运行启动后补充的目录枚举失败修复由此文件完整回归及 Spec 复核验证。
- 相关后端回归初次 76 项中，旧的“外部删除代码后仍用旧版本修复”断言失败。已按新契约改为重读列表版本后再修复，针对性回归通过；完整结果另记于下方。
- 审查前相关前端 64 项通过，首轮前端全量 391 项通过；审查修复后再次全量包含 392 项，其中 391 项通过，既有真实 Vite 端口测试触发 20 秒超时。未修改该测试或超时；随后整份 `tauri-command.test.mjs` 9 项通过，真实 Vite 用例耗时 1.8 秒。完整日志 `13-frontend-full-final.log`、`13-tauri-command-rerun.log`，MCP 回归 `13-review-ui-green.log`。
- TypeScript、后端 ty、变更 Python 文件 Ruff 与格式检查通过。最终 Vite 生产构建通过（35.69 秒），只有既有 chunk 大小提示，日志 `13-build-final.log`。
- Windows 原生用正式构建、真实后端／配置／代码文件验收，检查冲突、提交警告和实际提交后丢失响应；1 项通过（10.196 秒）。1440px／390px 无横向溢出，桌面主导航 64px、侧栏 256px、操作栏 48px、双栏 7:5。已查看两种宽度的冲突与警告截图，提示可读、恢复入口可见。截图在 `verification/native/test_config_conflict_committed_warning_and_unknown_save/`；测试 `13-native-final.log`。

## 后续调整：清理失败只记日志并在后续操作重试

2026-10-23 用户确认取消接口及前端清理警告。配置替换仍是提交点；每次配置提交之后和后端启动时重新读取引用、尝试清理，失败只记日志。没有失败队列、定时任务或新的确认接口。创建只返回 ID，更新／删除成功返回空 204；保存失败、版本冲突和未知结果的原有处理保留。

清理统一放在配置提交入口，因此工具、连接与批次提交都能重试此前残留；启动入口覆盖共享 `open_runtime` 和注入 runtime 的 HTTP lifespan。清理与源码读取使用同一协调锁，取消者也等待文件操作收尾。

本轮验证（不代表重新运行上方历史全量或双轴审查）：

- 后端相关 101 项通过（99.588 秒，`13-cleanup-retry-backend.log`），涵盖工具库、Python、HTTP 应用 lifespan 与 runtime。之后补充的 API／真实文件专项最终 14 项通过（15.771 秒，`13-cleanup-retry-api-final.log`），覆盖 Windows 占用时创建／更新／删除成功、只记日志、后续写入重试、启动清理、坏配置时跳过清理且后续连接保存重试。
- 前端客户端与工具页 50 项通过（`13-cleanup-retry-dom.log`、`13-cleanup-retry-dom-direct.log`）；TypeScript、后端 ty、变更 Python 的 Ruff／格式检查通过。
- Vite 生产构建通过（1 分 41 秒，`13-cleanup-retry-build.log`），只有既有 chunk 大小提示。
- 原生 `test_config_conflict_cleanup_retry_and_unknown_save` 1 项通过（7.853 秒，`13-cleanup-retry-native.log`）。验证占用时仅展示普通成功、解除占用后通过连接保存触发清理，以及刷新读取新版本后实际提交再丢失响应的恢复；1440px／390px 布局断言保留。截图在 `verification/native/test_config_conflict_cleanup_retry_and_unknown_save/`。
