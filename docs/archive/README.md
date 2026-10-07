# 历史材料与证据归档

最新整理见 [2026-10-07 开发文档归档](2026-10-07/README.md)和[开发交接](../development-handoff.md)。下面保留 2026-10-02 的归档背景；最新目录与验证范围以新索引为准。

归档日期：2026-10-02。先查 [文档导航](../README.md)、[Windows 收尾摘要](../windows-backend-lifecycle.md) 和 [研究索引](../research/README.md)。本次只整理材料与校正文档阶段信息，没有重新运行产品测试或重新核验外部项目。

## 归档包

| 文件 | 内容 | 需要时怎么找 |
| --- | --- | --- |
| [research-originals.zip](2026-10-02/research-originals.zip) | 11 份原始研究报告，完整日期、出处、长比较表、示例和未采用建议 | ZIP 内 `docs/research/<旧文件名>` |
| [windows-history-and-evidence.zip](2026-10-02/windows-history-and-evidence.zip) | 原 PRD、10 张已完成票、早期规划、长讨论、各轮测试日志/JSON/截图、临时 UI 脚本和 temp 便签 | ZIP 内 `.scratch/windows-backend-lifecycle/` 或 `docs/` 原路径 |
| [visual-explorations.zip](2026-10-02/visual-explorations.zip) | 历史设计探索图片、prompts、前端页面框架阶段截图及下载附属文件 | ZIP 内 `design/` 或 `frontend/work-records/assets/` 原路径 |
| [edited-documents-before-cleanup.zip](2026-10-02/edited-documents-before-cleanup.zip) | 本次改写文档的整理前版本 | 以仓库相对路径查原文件 |
| [manifest.json](2026-10-02/manifest.json) | 归档源文件的原路径、包名、大小、SHA-256 | 搜索旧文件名或所属主题 |

ZIP 统一保存仓库相对路径。需要回看时，解压到单独目录即可还原原始目录结构，旧文档互相引用也便于追踪；不要直接覆盖当前工作区。整理前逐包检查完整性，并逐文件比较解压内容与源字节，确认一致后才移除散文件。

## Windows 历史与验收

当前实施和最终结果见 [收尾摘要](../windows-backend-lifecycle.md#最终验收依据)。ZIP 内日志原路径前缀为 `.scratch/windows-backend-lifecycle/`：

- 最新基线：`test-results-10-windows-all.log`、`test-results-10-python.log`、`test-results-10-rust.log`、`test-results-10-client.log`、`test-results-10-build.log`、`test-results-10-native-build.log`。
- 首次联合失败及修正背景：`test-results-10-windows-initial.log` 和 `issues/10-startup-log-view.md`。
- 最新截图和结构化结果：`log-acceptance/`、`log-regression/`；早期阶段保存在其他 acceptance/regression 目录。
- 用户确认过程：`docs/wayfinder/windows-backend-lifecycle/tickets/002-runtime-contract.discussion.md`；早期规划：`docs/windows-backend-lifecycle-plan.md`。

日志和 JSON 可由现存测试重新生成，截图也属于对应代码阶段的证据，不需要全部作为活跃文档。此次集中压缩保存便于追溯，未永久丢弃失败记录。第 10 票联合 runner 保留在 [.scratch 原路径](2026-10-07/unresolved-issues-evidence.zip)（包内：`docs/archive/2026-10-07/development/windows-backend-lifecycle/run-10-windows.py`）。

## 调查原文

| 现在读什么 | 原报告文件名（均在 ZIP 的 `docs/research/` 下） |
| --- | --- |
| [持久化与运行边界](../research/persistence-and-runtime.md) | `agent-persistence-ownership-research.md`、`agent-runtime-boundary-comparison.md`、`deepseek-harness-persistence-research.md`、`agent-message-state-research.md`、`interrupt-resume-api-research.md` |
| [子 Agent 与多会话](../research/subagents-and-sessions.md) | `01-subagent-construction-and-runtime.md`、`02-multi-session-agent-landscape.md`、`03-child-session-lifecycle-control.md` |
| [MCP](../research/mcp.md) | `deerflow-mcp-config.md`、`deerflow-mcp-null-handling.md`、`mcp-startup-latency-mainstream-agents.md` |

原报告可能指向当时 WSL 路径、移动的上游分支和已经替换的项目 API。比如历史 resume 建议创建新 Run，与当前同 Run 恢复不同；摘要已经标出，原文保留作为背景而非新开发指令。

## 其他材料的处理

- `doc/1.txt` 和 `doc/带你一行行走读 run_agent().md` 是学习/开发指导，保留原文；总导航补上入口。
- `learning-records/`、`lessons/`、`AGENTS.md`、`NOTES.md`、`MISSION.md`、`RESOURCES.md` 与 `docs/agents/` 保留。教学进度不能直接替代产品实施进度，本次未重写教学约定。
- `docs/project.md`、前端 PRD/设计规范、数据独占/Python 启动器指导、LangGraph API 参考和 Windows 机制依据保留。闭合 Wayfinder 地图、票据和 resolution 保留，只有长讨论压缩归档。
- 两份 HTML demo 与 `design/design.md` 保留，属于现有设计规范引用的基准。原探索图片/prompt 与 2026-09-24 工作台截图集中归档。
- `.shikigen/` 实际运行数据、`.env`、配置文件、根目录 `output.json`/`todo`、应用图标、测试代码、依赖与构建目录未纳入清理；它们无法仅凭名字判断为可删除文档产物。
- `docs/temp.md` 只有旧迁移文件名与完成便签，浓缩价值不足，原内容进入 Windows 历史包。

以上描述本次实际处理范围，不新增协作约定，也不操作 Git 索引、暂存或提交。
