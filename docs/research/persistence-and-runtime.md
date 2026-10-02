# 持久化、执行边界与恢复

合并原持久化职责、运行边界、DeepSeek Harness 专项、消息状态、Interrupt/Resume 五份调查。主要调查日期为 2026-08-16、2026-09-14；消息状态文针对已移除的早期 `main.py`。上游资料未在本次整理中重新核验，原文及所有出处见 [归档](../archive/README.md)。

## 先分清保存的对象

| 对象 | 作用 | 边界 |
| --- | --- | --- |
| 完整消息与 transcript | 下一轮上下文、历史展示 | 不等于执行 checkpoint |
| Graph checkpoint | 暂停位置、可恢复状态 | 不自动保证外部工具副作用只执行一次 |
| Thread / Run 与事件事实 | 产品查询、执行状态、流重连对账 | token delta 不是权威历史 |
| 长期 memory | 跨会话知识 | 与会话 transcript 分开 |

保存时机、逻辑所有者、物理读写实现、进程启动装配是四件事。HTTP 与 CLI 应复用 run runtime；协议入口负责请求/响应，runtime 协调执行和结算，saver/repository 执行存储，composition root 打开和关闭资源。这是原调查对本项目的设计推论；当前落地约定见 [项目开发参考](../project.md)。

## 主流样本保留的关键差异

| 项目 | 历史调查所见 | 可以借鉴什么 |
| --- | --- | --- |
| DeepSeek Harness | Session/agent-loop 记录事件，checkpoint-policy 在模型、顶层工具、pre-step 边界 `flush()`；JSONL provider 管读写、锁、压缩和物理修复；headless 不需要 HTTP | `append()` 接受写入与 `flush()` 耐久屏障分开；保存策略和 provider 分开 |
| OpenClaw | Gateway 是会话权威与运行控制服务；runtime 驱动 transcript 保存，写入 owner 防止旧执行覆盖；历史调查基线为 per-agent SQLite | Gateway 可以较厚，但不要重复实现执行 Loop 或无条件重复保存消息 |
| Hermes | Agent 正常保存 transcript；共享 SessionDB 提供 SQLite；Gateway 管平台路由/交付，异常补写检查输入归属 | 正常写入与异常补写应有明确归属；会话连续性不等于任意工具中途恢复 |
| DeerFlow | Gateway lifespan 装配 persistence/checkpointer，harness worker 接收运行依赖并执行 | 入口装配资源不代表执行语义依赖 HTTP |
| LangGraph / Agent Server | OSS runtime 使用注入 checkpointer；托管 Server 装配资源，worker 执行 graph | checkpoint、Store 与服务 Thread/Run 资源分别建模 |

DeepSeek 恢复由 provider 解码日志，agent-loop 补齐中断 turn 的结束事实；不能理解为恢复工具函数调用栈。OpenClaw 的会话恢复和 compaction、Hermes 的消息恢复也不自动证明任意执行步骤可以重放。

其他原始样本包括 OpenAI Agents SDK、Claude Agent SDK、Pydantic AI、Letta，详细接口对照保存在 ZIP 原文。Pydantic AI 的消息历史、StepPersistence 快照与 Temporal durable workflow 是不同能力，不宜归并成一个“支持恢复”。

## 消息与流式语义

- `values` 是完整状态快照，应用于替换本地镜像；重复追加会复制历史。
- `updates` 是节点提交的状态更新；按消息身份合并。
- `messages` 是 token/chunk 展示流；完整消息事实应来自执行提交边界。
- SSE 断线只影响观察；重新订阅不能隐式再次发送消息、创建 Run 或恢复 graph。
- 终态先完成持久结算再发布；EOF 不能充当成功事实。当前 seq、message_id 与事务规则见 [项目消息契约](../project.md#消息与观察)。

## 审批与恢复：保留历史建议，但明确当前选择

必须分别建模新消息、回答已有 interrupt、重连观察。LangGraph 恢复使用 `Command(resume=...)`，审批答案不伪装成新的普通 HumanMessage。

2026-08-16 的原调查以“一次 invocation 一个 Run”为前提，建议 resume 创建新 run_id。这是历史方案。**当前 shikigen 采用同一个持久 Run 内的暂停与恢复**；新的 invocation 不等于新的产品 Run。以 [当前审批契约](../project.md#暂停与同-run-恢复) 为准，避免将旧建议重新实现进项目。

原调查中的差异：DeerFlow 通用 runs API 的 checkpoint resume 与 Web clarification 两条路径不同；Hermes/OpenClaw 的 inline approval 与重新调用 graph 不可直接等同。外部 UI/SDK 有恢复 API，也不代表主 LLM 自动获得控制工具。

## 原始来源与查找

- [DeepSeek Harness 架构](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/architecture.md)、[持久化契约](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/subsystems/persistence.md)
- [OpenClaw Agent Loop](https://docs.openclaw.ai/concepts/agent-loop)、[会话存储](https://docs.openclaw.ai/reference/session-management-compaction/store)
- [Hermes Session Storage](https://hermes-agent.nousresearch.com/docs/developer-guide/session-storage)、[Agent Loop](https://hermes-agent.nousresearch.com/docs/developer-guide/agent-loop)
- [LangGraph 持久化](https://docs.langchain.com/oss/python/langgraph/persistence)、[流式语义](https://docs.langchain.com/oss/python/langgraph/streaming)

`research-originals.zip` 内保留 `docs/research/agent-persistence-ownership-research.md`、`agent-runtime-boundary-comparison.md`、`deepseek-harness-persistence-research.md`、`agent-message-state-research.md`、`interrupt-resume-api-research.md`。原文件路径、大小和 SHA-256 可在归档清单查询。
