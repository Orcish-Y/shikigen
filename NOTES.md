# Teaching Notes

## 用户偏好
- **需求驱动学习**：不要直接写代码给他。描述需求、API、验收标准，让他自己实现，然后 review
- **中文交流**：所有教学对话用中文
- **先讲架构再动手**：对一个新模块，先解释它在 deer-flow 中的位置和设计原因，再给任务
- **宽松的边界**：他会主动超出任务范围（写了 sync 版本、加了测试、写文档），不要限制

## 风格
- 代码 review 时：先列做得好的，再列需要修的，最后列值得讨论的
- 每个需求说清楚三件事：做什么、为什么、用什么 API
- 接受他的幽默感（猫娘 agent 之类）

## 当前进度

### 阶段 1：Agent Loop ✅
- [x] 理解 Agent Loop 的核心概念（LLM → 工具 → LLM 的循环）
- [x] 能独立用 `create_agent` + `astream_events` 搭建可运行的 agent
- [x] 能定义 `@tool` 并正确管理消息历史
- [x] 多频道流式消费（messages / tool_calls / values）

### 阶段 2：工具 + Middleware + 工厂 ✅
- [x] 工具注册中心（ToolRegistry）
- [x] Middleware 链（ErrorHandling + Logging）
- [x] Agent 工厂（create_lead_agent）
- [x] 执行循环抽象（run_agent_loop）

### 阶段 3：Runtime 基础设施 ✅
- [x] StreamManager / pub-sub 事件流
- [x] Abort 取消机制（asyncio.wait + FIRST_COMPLETED race）
- [x] RunManager（run 生命周期）
- [x] Checkpoint 持久化（BaseCheckpointSaver 完整实现）

### 阶段 4：扩展与优化
- [ ] Token 统计与使用追踪
- [ ] 真实 web 工具（httpx + readability）
- [ ] 多轮 Goal 续跑
- [ ] 子 Agent 委派

### 前端工作台：设计与页面框架 ✅（2026-09-24）

- [x] 根据两份 HTML demo 整理 [前端设计规范](frontend/design.md)
- [x] React/Tauri 页面框架：导航展开/收起、历史、消息与代码区块、输入区、命令面板、详情空态
- [x] 本地过滤、新建会话、草稿隔离、代码复制、Markdown 导出与响应式布局
- [x] TypeScript/Vite 构建通过，四种窗口尺寸完成 Chromium 验证
- [ ] 真实会话与 HTTP/SSE 接入、运行状态投影、审批/取消/恢复、真实用量
- [ ] Tauri 原生窗口启动与打包验收

本阶段由用户明确委托助手实现；当前是示例数据驱动的页面框架，发送禁用，会话与草稿刷新后重置。
完整归档与截图见 [前端工作台项目工作记录](frontend/work-records/2026-09-24-workbench.md)。

## 技术环境
- Python 3.12, uv 包管理, ruff linter
- 模型：deepseek-v4-flash (via LangChain)
- 参考项目：deer-flow (`~/code/deer-flow`)
