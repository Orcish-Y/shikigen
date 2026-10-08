# Changelog

本文件记录 Shikigen Agent 的所有重要变更。格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

## [0.1.0] - 2026-10-08

首个正式版本。从 2026 年 7 月的学习项目成长为完整的 Agent 桌面系统：Agent Harness 框架包、FastAPI 流式服务端、Tauri 桌面工作台。

### Added

#### Agent Harness（`packages/harness/shikigen`）

- **Agent 工厂与执行循环**：`create_lead_agent` / `run_agent_loop`，基于 LangGraph `astream_events` 的 token 流、工具调用、取消（`asyncio.Event` + `FIRST_COMPLETED` race）
- **StreamManager**：内存 pub/sub 事件流，解耦生产者与多消费者
- **RunManager**：Run 生命周期状态机（PENDING → RUNNING → terminal），同 thread 互斥，优雅释放与 shutdown
- **Checkpoint 持久化**：JSON 文件与 SQLite 两种 checkpointer，对话历史跨重启恢复
- **Goal 续跑 middleware**：`/goal` 目标设置后自动评估（`GoalEvaluator`）与 `jump_to` 续跑，带轮次断路器；`state_schema` 随 checkpoint 持久化
- **Token 统计**：`TokenTracker` callback handler，三路径兼容 usage 格式，按模型分拆
- **子 Agent 委派**：`task` 工具（general / bash 两种子 Agent），闭包工厂注入模型与工具注册表
- **审批（Human-in-the-loop）**：危险操作前暂停 graph，等待人工批准后恢复同一 run

#### 工具系统（`shikigen/tools`）

- **ToolRegistry**：多来源工具收集、按名去重（warning + skip）
- **沙箱工具**：`bash`（超时 + 输出截断）、`list_dir`、`grep`（纯 Python，跳过噪声目录）、`read_file` / `write_file`（`Path.relative_to` 路径逃逸防护）
- **Web 工具**：Jina AI 抓取 + Readability 正文提取 → Markdown；百度千帆搜索（结构化结果格式化）
- **MCP 加载器**：`MultiServerMCPClient` 集成，stdio / http 双 transport，per-server 隔离重试与并行发现

#### 配置系统（`shikigen/app_config`）

- Pydantic `AppConfig`（`extra="forbid"`），MCP server 配置 discriminated union（http / stdio）
- `$ENV_VAR` 环境变量递归解析（密钥不入库）
- `config.json` 驱动模型选型、MCP servers

#### 服务端（`app`）

- FastAPI：会话（threads）、消息（messages）、运行（runs）REST API
- SSE 流式协议：`metadata` / `delta`（content 与 reasoning 分字段）/ `message.created` / `lifecycle.status_changed` / `approval.required` / `usage`
- SQLite 持久化：threads、runs、run_events 三表（WAL、外键、稳定幂等 key）
- **Run observation + SSE 重放**：断线后全量重建事件流并跟随活跃 run
- **审批续跑 API**：`approval-decisions` 提交后恢复同一个 Run 的流
- Run 取消、用量结算（usage_pending 语义）
- **运行时恢复**：进程重启后孤儿 run 回收

#### 桌面工作台（`frontend`）

- Tauri 2 + React 19 + Vite 7 + Tailwind CSS 4 + TypeScript
- 托管 Python 后端生命周期：托盘常驻、单实例启动、启动日志查看器、受限重试
- 会话管理：分页历史、草稿恢复、阅读位置、导出（含完整工具记录）
- 流式体验：delta 按 message_id 聚合、run 从持久化事件重建、断线观察恢复、窗口可见性刷新
- 审批卡片与审批草稿恢复、工具记录展示、用量核对
- Markdown 查看器（rehype-sanitize 消毒）、工作区文件打开与图片预览
- 命令搜索（⌘K）、响应式导航、桌面偏好

#### 测试

- 后端：227 个 unittest（Agent 工厂、loop、stream、run manager、checkpoint、审批、恢复、工具、契约）
- 前端：28 个测试文件（流恢复、run 重建、审批草稿、用量结算、分页、可见性轮询、工作区快捷键）

### 架构决策

- **Harness / App 分层**：`app` 依赖 `shikigen`，`shikigen` 永不反向依赖（单向边界）
- **Contracts 层**：消息、事件、Run 状态的跨层类型契约独立成包
- **Runtime 装配**：`open_runtime()` / `assemble_runtime()` 封装生命周期，HTTP 应用只消费 Runtime 对象
