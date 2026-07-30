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
- [x] 理解 Agent Loop 的核心概念（LLM → 工具 → LLM 的循环）
- [x] 能独立用 `create_agent` + `astream_events` 搭建可运行的 agent
- [x] 能定义 `@tool` 并正确管理消息历史
- [ ] 工具注册中心（ToolRegistry）
- [ ] Middleware 链
- [ ] 事件流/StreamBridge
- [ ] Checkpoint 持久化

## 技术环境
- Python 3.12, uv 包管理, ruff linter
- 模型：deepseek-v4-flash (via LangChain)
- 参考项目：deer-flow (`~/code/deer-flow`)
