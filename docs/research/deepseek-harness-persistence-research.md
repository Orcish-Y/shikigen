# DeepSeek Harness：持久化职责调查

调查日期：2026-09-14。对象：[deepseek-ai/deepseek-harness](https://github.com/deepseek-ai/deepseek-harness)，本次读取官方 `master` 文档与源码；链接未固定 commit，后续调查需重新核实。

## 结论

**逻辑职责属于 harness runtime 的 Session/agent-loop 与持久化插件，HTTP server 不是必要条件。** 官方架构把 persistence 放进 Web、headless、SDK、ACP 共用的 `dsh-base`；headless 明确没有 server。因此“运行在后端进程”和“由 HTTP server 层负责”不能混为一谈。[架构文档](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/architecture.md)

## 做什么、为什么、用什么 API

| 职责 | 做什么与为什么 | API / 所属模块 |
|---|---|---|
| Session 领域模型 | 保存结构化事实，再从事件推导模型历史，避免另一套历史与执行记录漂移 | `SessionEventMap`、`session.append()`、`deriveMessages()`；`packages/core/session` |
| 执行生命周期 | 创建/恢复 Session 并持有写句柄，避免两个执行者同时恢复和写入 | `ctx.agents.create()`、`ctx.agents.resume({ resumeSessionId })`；`packages/core/agent-loop` |
| 保存时机策略 | 模型请求前、顶层工具执行前、下一步之前等待持久化；失败则不进入相应模型或工具调用 | `ctx.sessions.flush()`；`dsh-session-checkpoint-policy` |
| 存储抽象 | 用每会话句柄集中读写与单写者所有权 | `ctx.sessionPersistence.create/open/stat/list`；`SessionHandle.read/append/flush/close` |
| 物理存储 | 编码、批量写入、压缩、文件锁与物理尾部恢复 | `dsh-session-persistence-jsonl` |

来源：[Session 模型](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/subsystems/session.md)、[存储契约](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/subsystems/persistence.md)、[checkpoint-policy 实现](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/session/session-checkpoint-policy/src/index.ts)、[agent-loop 实现](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/core/agent-loop/src/index.ts)。

## 实际数据位置与写入链路

官方 base 配置将 JSONL provider 的 `root` 设为 `dshHomePath('sessions')`。同时把通用 JSON KV 放到 `dshHomePath('storages')`。搜索索引另有 SQLite 插件；这份默认配置为 `path: ':memory:'`、`openAt: never`，不能把 SQLite 搜索误认为会话日志的主存储。[base 配置](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/bundle/base/cordis.patch.yml)

会话文件组织为 `$DSH_HOME/sessions/<project-key>/<encoded-session-id>/session.vN.jsonl[.zstd]`；旧 v0 文件名不含 `.vN`。项目 key 来自 cwd，无 cwd 时使用 `_no-cwd`。默认使用 Zstandard，也可以配置不压缩。provider 自身要求显式 root，并在初始化时解析为绝对路径。[路径实现](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/session/session-persistence-jsonl/src/format.ts)、[provider 实现](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/session/session-persistence-jsonl/src/index.ts)

普通日志事件经同步 `session/event` 通知进入 provider 的批量写入缓冲；`session/flush` 排空待写事件。抽象接口中 `append()` 成功表示接受并可见，只有 `flush()` 是明确的持久化屏障。关闭写句柄也会完成剩余持久化。[持久化文档](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/subsystems/persistence.md)

## 恢复边界

源码中 `resumeWith()` 先 `persistence.open(id, 'write')`，再读事件，用 `interruptedTurnClosers()` 补缺失的工具错误、step 结束和 interrupted turn 结束事件，然后准备并发布恢复后的 Session。**物理日志解码由 provider 做，执行语义修复由 agent-loop 做。**[恢复实现](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/core/agent-loop/src/index.ts#L798)

完整 assistant stream 在一次响应结算时作为事件保存；实时 chunk 是进程内事件。硬崩溃发生在结算前时，没有这次 attempt 的持久化 stream。[架构文档：Session log](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/architecture.md#session-log)

**推论**：这是从事件恢复上下文和执行边界，不等于恢复正在运行的工具函数调用栈，也不能据此宣称外部副作用 exactly-once。checkpoint-policy 确保调用前的记录先落盘，但工具已经产生副作用、结果尚未保存的情况，仍需具体工具或业务幂等机制处理。

## 对本项目的启发（设计推论）

可借鉴的是将“何时必须保存”作为 runtime 的策略，将“怎么读写”作为可替换接口：runtime 知道请求、工具与 step 边界；应用入口决定装配哪种存储及其路径。不能仅因 Web 模式持久化文件位于服务端主机，就把保存语义归到 HTTP 路由层。
