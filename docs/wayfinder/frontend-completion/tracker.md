# 首版前端补全的本地 Markdown tracker

本目录沿用 [仓库 issue tracker](../../agents/issue-tracker.md) 和既有 Windows 地图的本地追踪方式。

## Wayfinding operations

- map.md 为地图；tickets/ 下的 Markdown 为子票据。front matter 的 id 是稳定身份，title 是面向读者的名称，parent 指向地图身份。
- labels 使用 wayfinder:map 或 wayfinder:grilling / wayfinder:task。mode 标明 HITL 或 AFK，不替代状态。
- status 为 open / closed；assignee: null 为未认领。工作前先将 assignee 设置为实际驱动者。HITL 票据通过与用户的真实交流解决，不能由 agent 代替用户作决定。
- 没有原生阻塞关系，以 blocked_by 数组表示依赖。创建全部票据后第二次更新依赖；任何依赖未关闭时，不进入 frontier。
- 查询 frontier：读取 tickets/ 元数据，筛选 status: open、assignee: null，且 blocked_by 中所有票据已 closed；按文件名升序选择。只读取所选票据正文，相关材料按需读取。
- 所有用户可见引用使用标题链接，不以编号或 slug 代替票据名称。map.md 不重复列开放票据；它只记录已关闭票据的一行索引。
- 票据正文保留 Question。结论写入同目录的同名 .resolution.md，作为 resolution comment；票据补 resolution 字段并 closed，再向地图 Decisions so far 追加标题链接与概要。
- 建图会话只建图，不同时解决票据；每个后续会话最多解决一个票据。需要新增问题时先创建票据，再补依赖。
- 如果后续决定将某票据移出范围，关闭并把标题链接与原因放入地图 Out of scope，不计为 Decisions so far。

票据状态只表示规划决策进度；实施任务和测试是否通过需要单独记录，不能由地图 closed 推断。
