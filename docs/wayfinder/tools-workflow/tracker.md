# 工具模块的本地 Markdown tracker

沿用[仓库 issue tracker](../../agents/issue-tracker.md)。

## Wayfinding operations

- `map.md` 是唯一地图，`tickets/` 中每个非 `.resolution.md` 文件是子票据。front matter 的 `id` 是稳定身份，`title` 是用户可读名称，`parent` 指向地图身份。
- 仅使用 `wayfinder:` 标签；`mode` 为 AFK 或 HITL，`status` 为 open 或 closed。`assignee: null` 表示未认领，工作前先填写驱动者。
- 本地 tracker 无原生依赖关系，以 `blocked_by` 表示阻塞。先创建全部票据，再第二次填写依赖，不使用占位编号。
- frontier 为 open、未认领且全部依赖已 closed 的子票据，按文件名排序。地图不列开放票据。
- 票据正文保存问题；答案作为同名 `.resolution.md` 保存，票据添加 `resolution` 并 closed，地图只追加标题链接和一句结论索引。
- HITL 票据必须通过用户实际参与解决；建议和代码结构推断不代表用户已确认。
- 建图阶段允许 research 子代理完成调查票据，其他票据留待后续逐票讨论。处理地图时每次最多解决一个非 research 票据。
- research 产物保存在 `docs/research/`，另存到 `research/<name>` 临时分支并推送，不开 PR、不合并。当前工作区、Git 索引及用户既有文件必须保留。
- 规划 closed 不表示产品已实现或已验收。移出范围的票据 closed 后只索引在地图 Out of scope。

