# Changelog

本文件记录 Shikigen Agent 的所有重要变更。格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

## [0.2.0] - 2026-10-25

可复用工具库与统一扩展页面。支持直接执行或按稳定 ID 组装工具，为后续工作流与定制 Agent 提供复用入口。

### Added

- **持久工具库**：创建、编辑、启用／禁用、删除和搜索工具；输入／输出结构、调用名称校验、完整结果查看与复制。
- **HTTP 工具**：方法与地址模板、path／query／headers／JSON body 映射，Bearer 与 API Key 认证；OpenAPI 3.0／3.1 JSON／YAML 预览、兼容诊断和批量导入。
- **Python 工具**：CodeMirror 6 + Lezer 源码编辑和本地参数预览，后端权威解析；类型补齐、源码变更同步、真实子进程执行及调试输出。
- **MCP 工具**：stdio 和 Streamable HTTP 连接管理、连接测试、发现预览、选中入库、重新发现更新及连接删除；保留远端完整结果和本地稳定身份。
- **草稿与测试生命周期**：未保存配置可直接测试；后端生成测试 ID，支持查询、取消、超时、资源清理和执行观察中的已知认证值脱敏。
- **保存与复用**：配置及 Python 源码版本冲突检查、整批提交、本次调用快照；`get_tool()`、`build_tools()`、`execute_tool()` 及同步脚本入口。
- **开发资料**：工具页原型参照规则、14 张开发票、实现／审查记录和验证入口集中纳入版本化文档。

### Changed

- **统一扩展导航**：对话和扩展共用主导航；扩展库集中展示全部／工具／MCP／SKILL 分类、搜索、新增入口与隐藏禁用工具开关，沿用既有编辑和离开保护。
- **表单与结果组件**：接入 shadcn/ui、rjsf 和 AI Elements，保留 JSON、null、false、0、空字符串及复杂 schema 的真实语义。
- **工具模块归属**：工具库、执行器、适配器和调用桥接集中到 `shikigen.tools`；注册和 Agent 组装归 `shikigen.core`。原内部模块路径已移除，未保留兼容导出。
- **保存响应**：创建返回稳定 ID，更新／删除成功返回 204；保存成功后读取详情失败与保存失败分别处理。旧 Python 文件清理失败由后端记录并在后续提交或启动时重试。

### Fixed

- 应用完整启动时显示新会话欢迎页，不自动恢复旧会话选择；首次发送才创建会话，保留输入原文和历史草稿，托盘恢复保留当前会话。
- Bearer 认证值已带前缀时避免重复添加；工具业务参数 `type="tool_call"` 不再被误认为完整 LangChain 调用封装。
- 同步、异步和跨事件循环调用共用实际执行链路；取消、超时和关闭等待资源清理，避免重复取消打断清理。

### 发布范围

- 本次发布源码及 Git tag，Windows 安装包和 Python 随包分发仍需单独验收。
- 统一凭据存储与隐藏编辑协议、Python `async def main`、完整工作流编辑器、定制 Agent 页面、当前聊天自动挂载和 MCP 会话池仍留待后续开发。

验证结果、首次异常与覆盖边界见[发布验证记录](docs/releases/v0.2.0-validation.md)。

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
