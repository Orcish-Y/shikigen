# 工具库文档整理记录

整理于 2026-10-23，代码基线 `c42a50f`。当前开发从[工具库开发指南](../../../wayfinder/tools-workflow/README.md)进入，阶段结果从[验证与报告索引](../../../wayfinder/tools-workflow/validation.md)查找。本次只整理文档及入口，没有运行产品验收或更改应用行为。

## 保存位置

| 材料 | 长期位置与用途 |
| --- | --- |
| 原 `.scratch/tools-workflow/PRD.md` | [历史 PRD](PRD.md)：保留 66 条用户故事、拆票依据及当时的待实施说明 |
| 原 `.scratch/tools-workflow/README.md` | [任务发布索引](task-index.md)：保留原任务依赖及发布时的状态，供追溯 |
| 原 `.scratch/tools-workflow/issues/01–14` | [实施目录](../../../wayfinder/tools-workflow/implementation/index.md)：保留票据正文、状态、验收项和完成记录，修正迁移后的相对链接 |
| 实现说明及 `.review.md` | 保留在 `docs/wayfinder/tools-workflow/`，以主题入口串联当前约定和阶段证据 |
| 原始调查及未实施方案 | 保留原位并标注阶段；Python async main 继续为待实施方案 |
| 日志、截图、探针及缓存 | 继续留在本机 `.scratch/tools-workflow/`，由[验证索引](../../../wayfinder/tools-workflow/validation.md#原始证据位置)说明范围 |

原 scratch 的 PRD、发布索引及 14 个 issue 路径改为跳转说明；同一正文只有上述一份长期维护位置。其余本机实验和证据文件保留原路径，阶段报告中的日志定位仍然有效。完成票与 PRD 已进入 Git 可跟踪目录，后续合并分支时可一并带入主仓库。

## 历史材料如何阅读

原 PRD 中 `ready-for-agent`、初始索引中“尚未实施”，以及旧阶段的凭据隐藏、测试登记、清理 warning 等文字保留原时间含义。每份迁入材料都有历史说明；当前差异由[开发指南](../../../wayfinder/tools-workflow/README.md)和对应主题最新修订说明。

07 原票的部分完成状态保留：stdio 主链路已实现，统一凭据管理仍延期。12 后来加入的执行观察脱敏单独记录，不能据此宣称凭据存储、隐藏读取和编辑协议全部完成。完整聊天 Agent 的同步调用、Python async main、工作流编辑器和当前聊天自动挂载同样没有作为既有能力列入。

本次也修正了认证实现记录中已过时的“没有执行结果脱敏”描述，并为开发前调查、规划地图及研究结论补上当前入口。历史测试数字、失败原因和审查结论保持原阶段含义。

## 整理检查

已检查本次涉及及工具专题内的 67 份 Markdown、562 个本地链接与章节锚点，均能解析，链接目标均在版本控制或本次新增文档范围内。迁移确认 14 张开发票的原状态与勾选项保持，PRD 的 66 条用户故事完整保留；原 scratch 入口指向长期正文。`git diff --check` 通过，应用、前端与测试源码均无改动，Git 暂存区未操作。
