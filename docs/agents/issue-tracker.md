# Issue tracker: Local Markdown

本仓库使用本地 Markdown 文件追踪需求与任务。

## 通用任务约定

- 每个 feature 一个目录：`.scratch/<feature-slug>/`
- PRD：`.scratch/<feature-slug>/PRD.md`
- 任务：`.scratch/<feature-slug>/issues/<NN>-<slug>.md`，从 `01` 编号
- 任务文件顶部用 `Status:` 记录 triage 状态；状态词汇见 `triage-labels.md`
- 评论和讨论追加到 `## Comments`
- `.scratch/` 或 feature 目录不存在时，首次使用时创建

## 已完成任务的长期保存

已完成 feature 的 PRD、开发票及实现／验收结论可整理到 `docs/` 中的对应专题，补充当前行为、历史范围和验证入口。原 scratch 路径保留指向长期正文的说明；后续查阅使用版本化正文，本机日志和缓存继续留在 scratch。工具模块的实例见[开发指南](../wayfinder/tools-workflow/README.md)与[实施索引](../wayfinder/tools-workflow/implementation/index.md)。新任务发布仍使用上面的 scratch 路径约定。

## 技能的 tracker 操作

- 技能要求发布 PRD 或任务时，在 `.scratch/<feature-slug>/` 下创建文件
- 技能要求读取已有任务时，读取用户提供的路径或编号对应的文件
- 本地 Markdown 不接收外部 PR 作为 triage 请求入口

## Wayfinding operations

- Wayfinder 地图和子票据沿用仓库现有位置：`docs/wayfinder/<effort>/map.md` 与该目录下的 `tickets/`
- 每个 effort 的 `tracker.md` 说明该地图使用的元数据、依赖、frontier 和 resolution 规则；处理地图时以该文件为准
- 已完成的 Windows 生命周期地图继续保留在 `docs/wayfinder/windows-backend-lifecycle/`，无需迁移
