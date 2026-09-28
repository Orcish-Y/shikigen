# 本地 Markdown tracker

本目录采用 wayfinder 在未配置外部 issue tracker 时的本地 Markdown 形式。

## Wayfinding operations

- 地图为 `map.md`，子票据位于 `tickets/`。每个文件的 front matter 中 `id` 是稳定身份，`title` 是面向读者的名称。
- 子票据使用 `parent` 指向地图身份，使用 `labels` 标注 `wayfinder:grilling` 等类型。
- `status` 为 `open` 或 `closed`；`assignee: null` 表示未认领。开始处理前，将 assignee 设置为实际驱动该票据的开发者。
- 此 tracker 没有原生依赖能力，以 `blocked_by` 数组记录依赖票据身份。先创建票据，再补充依赖。
- 查询 frontier：读取 `tickets/` 的元数据，筛选 `status: open`、`assignee: null` 且 `blocked_by` 中所有票据均已关闭的条目，按文件名排序。阅读时始终用标题链接引用。
- 票据正文只记录问题。结论以同目录下 `<文件名>.resolution.md` 作为 resolution comment 保存；随后关闭票据，在地图 Decisions so far 添加一行标题链接与概要。
