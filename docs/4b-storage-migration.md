# 4B：现有数据兼容与离线迁移

2026-09-16。实现：[迁移入口](../app/persistence/migrate.py)；测试：[迁移测试](../tests/test_storage_migration.py)。

## 位置与边界

迁移属于产品存储维护，位于 `app/persistence/`，不进入 Graph、HTTP 或应用启动流程。
`ChatStore.open()` 继续拒绝未迁移旧库；离线 API
`prepare_copy(source, destination, upgrade=False)` 使用 SQLite backup 创建一致副本，
审计后可通过 `upgrade=True` 升级该副本。来源以只读方式连接，目标必须不存在，
不覆盖已有文件，不自动切换配置。同步 API 供离线维护使用，不在运行中的事件循环调用。

**继续共用产品／checkpoint 数据库文件。**backup 同时复制 `checkpoints`、`writes`
及其他表；转换只重建产品表。保留 SQLite `user_version`，产品版本由 `chat_schema` 独立记录。
共用文件仍不代表产品事务、checkpoint 与工具副作用能够原子提交。

## 支持的版本与字段映射

版本 0：没有 `chat_schema` 的旧 ChatStore，支持 `run_events` 有／无 `event_key` 两种格式。
版本 1：4A 格式。再次执行只复制和审计，不重复合成事件。
未知版本、额外产品列、自定义产品索引／触发器、其他表引用产品表的外键均阻止升级，
避免重建时静默丢失扩展。版本 1 还核对建表／索引定义，不能只增加版本标记冒充已迁移。

| 旧字段 | 新字段／处理 |
| --- | --- |
| Thread 全部字段 | 原样保留，包括 `id/user_id/title/created_at/updated_at` |
| Run 既有字段 | 原样保留身份、归属、状态、错误文本和三个时间字段 |
| 无 `runs.error_code` | error 状态记为 `legacy_error`，表示历史错误未分类；其他状态 NULL，报告列出此变化 |
| 消息／事件 `id/seq` | 原样保留，不重新排序、不压缩序号；保留 AUTOINCREMENT 高水位 |
| `content_json/metadata_json/created_at` | 原字符串与时间不改写；先验证可被新接口读取、消息满足 4A 最低契约 |
| 非空 `event_key` | 原样保留；消息键必须与 payload 身份一致 |
| 缺列或 NULL 的消息 `event_key` | 从既有 message_id 推导 `human:/ai:/tool:` 键；工具允许既有 tool_call_id 回退；每项写入报告 |
| 非消息的 NULL `event_key` | 继续保留 NULL |
| 缺少当前 Run 状态对应的 lifecycle 事实 | 除 pending 外，追加带迁移标记的状态快照，详见下节 |
| 无产品版本标记 | 在升级事务内创建 `chat_schema(version=1)`，同时安装 4A 约束 |

不为缺少稳定身份的消息猜造 message_id，不补造工具结果，也不自动删除重复记录。
缺失／矛盾的完成时间不以 updated_at 代替，而是报告并阻止升级。

## 审计与历史不一致

JSON 报告包含 `source_version/target_version/counts/issues/changes/upgraded`。
`issues` 给出稳定问题码和相关 Thread、Run、事件 ID；不输出消息正文。
报告中的 `changes` 是计划变化，只有 `upgraded=true` 才代表已应用；
`preserve_nonterminal` 提醒旧非终态仍被保留，不代表已恢复执行。

以下情况阻止升级：

- 一个 Thread 有多个 pending/running/interrupted Run。
- 重复事件键、重复消息身份（包括同 Thread 跨 Run）、重复／非法 seq 或 ID。
- 缺少消息身份、消息类型／键不一致、无效 JSON 或 metadata、消息不满足 4A 契约。
- 孤立 Run／事件、外键或 SQLite 完整性错误、非法状态、状态与完成时间矛盾。
- 当前状态与既有 `running:{run_id}`／`settled:{run_id}` 事实不符。
- 不支持的 schema 版本或扩展。

即使重复消息内容相同，也不自动去重，因为删除会改变既有事件身份和历史。
先根据报告在另一个工作副本中核对原始事实、确定归属或状态，再重新审计；
迁移工具不提供自动“选一个 Run 保留”的修复开关。
失败时副本保持旧格式，可继续通过 SQLite 或对应旧版读取程序检查；新版 ChatStore
拒绝旧格式属于预期行为。事务遇到异常（包括取消）会回滚表结构和数据变更。

## 合成状态快照的含义

早期 Run 只有状态行，没有生命周期事件。迁移不反推历史执行时刻：

- 保留 Run 的原时间及所有原事件；新记录追加到该 Thread 最大 seq 之后。
- `created_at` 使用迁移时刻；metadata 中的 `migration.kind=status_snapshot`、
  `observed_at` 和 `historical_transition_time_known=false` 明确表示迁移观察。
- metadata 保留 `source_updated_at/source_completed_at`，供追溯；不将它们解释为准确事件时间。
- completed/error/cancelled/interrupted 快照使用 `settled:{run_id}`，running 使用
  `running:{run_id}`；pending 仅保留状态，不生成“已经开始”的事实。
- 已有对应事实原样保留；原本 interrupted 的快照不会补造 checkpoint 或审批信息。

保留旧 running/interrupted 不会创建本地执行句柄，也不使其自动可恢复；
启动恢复和审批恢复分别仍属第 8、7 步。缺少恢复坐标时不能据状态快照继续执行 Graph。

## 命令与切换步骤

先在副本上审计与演练（目标路径必须不存在）：

```bash
.venv/bin/python -m app.persistence.migrate \
  .shikigen/data/shikigen.db /tmp/chat-audit.db > /tmp/chat-audit.json
.venv/bin/python -m app.persistence.migrate \
  /tmp/chat-audit.db /tmp/chat-upgraded.db --upgrade > /tmp/chat-upgraded.json
```

退出码：0 表示审计通过；2 表示审计发现阻断问题、未升级；1 表示文件／SQL／执行错误。
默认不升级；即使指定 `--upgrade`，有阻断问题也只保留旧格式副本和报告。
backup 会纳入 WAL 已提交的数据，不能用单独复制 `.db` 文件替代。
在线演练副本只代表获取快照时的内容，不能拿旧演练副本直接切换生产。

实际切换须另行安排，本次未执行：

1. 停止 HTTP、Python 入口及其他写入进程，等待 Graph、结算与 checkpoint 连接关闭。
2. 保留原文件作为回滚来源；从停写后的来源创建新的迁移副本，检查报告。
3. 用新版 ChatStore 验证历史查询、schema 约束及 checkpoint 读取。
4. 同时将 `database.path` 与 SQLite `checkpointer.path` 指向该新文件，再启动新版。
   不允许产品路径切新库而 checkpoint 继续写旧库，也不同时启动新旧写入者。
5. 若尚未接收新写入，停止新版并把两个配置路径恢复原文件，使用兼容旧格式的应用版本。
   若新库已经有新增 Run／checkpoint，不能直接回退而丢弃新数据；先停写并单独核对、迁移增量。

## 2026-09-16 验证记录

对实际 `.shikigen/data/shikigen.db` 通过 backup 获取副本，原库未升级，配置未切换。
副本包含 1 个 Thread、1 个 completed Run、2 条完整消息；审计无阻断问题。
迁移仅新增 `error_code`、schema 约束／版本，以及 1 条带迁移标记的完成状态快照；
原产品记录和 checkpoint／writes 数据保留。原消息已有稳定身份，无需补消息键。

实际副本审计报告：`/tmp/shikigen-4b-audit.json`；演练新库：`/tmp/shikigen-4b-verified.db`。
临时文件可能被清理，上述结论在此留档。完整回归结果见 [实施清单](migration-checklist.md)。
