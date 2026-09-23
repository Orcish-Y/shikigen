# Shikigen Agent

## 项目结构

- `packages/harness/shikigen/`：框架包，包含 Agent、执行 Loop、运行时、工具和 middleware，使用 `shikigen.*` 导入。
- `app/`：应用层，包含 FastAPI 服务器，依赖 `shikigen`。
- `app/routes/thread.py`：会话列表、创建会话、会话历史消息。
- `app/routes/run.py`：发起流式运行、查询运行消息；SSE 事件编码位于 `app/run_contract.py`。
- `packages/harness/shikigen/persistence/`：会话、运行与事件的 SQLite 持久化。
- `packages/harness/shikigen/checkpoint/`：Graph checkpoint 与连接管理。
- `packages/harness/shikigen/runtime/`：共享运行环境，包含装配、生命周期、会话与 Run 管理；对外入口为 `Runtime`、`open_runtime()`、`assemble_runtime()`。
- `tests/`：测试。

框架包内部按职责组织：

```text
shikigen/
├── __init__.py       # 公共 Python 导出
├── app_config.py     # 配置模型与加载
├── core/            # Agent 工厂、审批规则、Loop、Graph 适配与本地执行资源
├── runtime/         # 会话、持久 Run、审批、执行协调、装配与 CLI
├── contracts/       # 消息、事件、Run 状态及流载荷的数据模型
├── persistence/     # SQLite 事务和读写
├── checkpoint/      # Graph checkpoint 存取
├── tools/           # 工具与注册表
├── middleware/      # Agent middleware
├── callback_handler/ # 模型回调与 token 统计
└── utils/           # 通用辅助函数
```

`core` 负责一次 Agent 执行，不依赖 `runtime` 或业务数据库；`runtime`
将执行与 `persistence` 组合成可持续查询、取消和恢复的 Run。
共享数据模型放在 `contracts`，存储层不再导入 runtime。
`core/approval.py` 集中工具审批策略、middleware 构建和人工决策校验；
runtime 负责审批对应的 Run 状态检查、持久化与恢复执行。
`core/stream.py` 实现内存广播，`contracts/stream.py` 定义其载荷；
`contracts/events.py` 定义事件内容，`runtime/run_events.py` 负责接入与写入协调。
旧的纯内存 `RunManager` 位于 `core/run_manager.py`，供 `run_agent_loop()` 使用；
持久运行使用 `runtime.runs.RunService`。

公共导入 `from shikigen import create_lead_agent, execute_agent_loop` 和
`from shikigen.runtime import open_runtime` 保持不变。直接引用旧内部模块的代码
需改用 `shikigen.core.*` 或 `shikigen.contracts.*`；例如
`shikigen.loop` 改为 `shikigen.core.loop`，`shikigen.runtime.run_state`
改为 `shikigen.contracts.runs`，`shikigen.runtime_context` 改为 `shikigen.core.context`。

根项目通过 uv workspace 依赖 `shikigen-harness`；`uv sync` 会以 editable 模式安装框架包。
以下命令均在项目根目录执行；默认配置 `config.json` 和运行数据路径相对于当前工作目录。

## 运行测试

```bash
uv run python -m unittest discover -s tests
```

## 独立运行 Agent

安装 harness 后，无需启动 FastAPI 即可运行并持久化一次对话：

```bash
uv run python -m shikigen.runtime --config config.json '你好'
```

沿用会话可传入 `--thread-id`。此命令需要配置中模型和 MCP 对应的环境变量；
若使用 `.env`，可在 `uv run` 后添加 `--env-file .env`。
Python 调用方通过 `from shikigen.runtime import open_runtime` 打开异步上下文，
使用 `runtime.threads` 和 `runtime.runs` 操作会话与运行；退出上下文时回收后台任务和存储连接。
旧的 `app.run` CLI 入口已迁移至 `shikigen.runtime`。

`runtime/runs.py` 中的 `RunService` 负责本地执行协调，`RunTransitions`
负责创建、结算、取消和审批恢复等持久状态变更。
这些操作通过 `ChatStore.transaction()` 将状态检查、状态更新与相关事件一起提交。
事件写入统一经过 `runtime/run_events.py`：生命周期操作调用
`RunEventIngestor.write_in_transaction()` 使用已有事务，完整消息通过
`ingest_message()` 接入。事件层不决定 Run 状态，不自行提交调用方的事务；
只有提交成功后才广播。SQL、序号分配和回滚留在 persistence。

## 启动 Web 服务器

先在项目根目录安装依赖：

```bash
uv sync
```

在项目根目录创建 `.env`，配置模型和 MCP Server 所需的环境变量。当前 `config.json` 启用了 GitHub MCP，因此至少需要提供：

```dotenv
GITHUB_TOKEN="Bearer github_pat_xxx"
```

请将示例值替换为真实 token。`.env` 已被 `.gitignore` 忽略，不要把密钥提交到 Git。

以开发模式启动 FastAPI，监听本机的 `8000` 端口：

```bash
uv run uvicorn app.server:app \
  --env-file .env \
  --host 127.0.0.1 \
  --port 8000 \
  --reload
```

等待终端显示 `Application startup complete` 后，可以打开：

- API 文档：<http://127.0.0.1:8000/docs>
- OpenAPI 定义：<http://127.0.0.1:8000/openapi.json>

启动过程中会初始化配置、MCP 工具、模型、SQLite checkpointer 和 agent。
请确保 `config.json` 以及模型所需的环境变量已经配置完成。

如果启动时出现下面的错误：

```text
AppConfigError: Config field "..." requires missing environment variable "GITHUB_TOKEN"
```

请确认 `.env` 中已经定义该变量，并且启动命令包含 `--env-file .env`。

### 测试接口

创建一个新的 thread：

```bash
curl -X POST http://127.0.0.1:8000/api/threads
```

复制响应中的 `thread_id`，然后发送一条消息并消费 SSE 事件流：

```bash
curl -N \
  -X POST http://127.0.0.1:8000/api/threads/<thread_id>/stream \
  -H "Content-Type: application/json" \
  -d '{"message":"你好，请介绍一下自己"}'
```

`curl -N` 关闭输出缓冲。响应类型是 `text/event-stream`，每帧包含 `event:` 和
`data:`，以空行结束。只有 `metadata`、`delta`、`event`、`error` 四类事件：

- `metadata`：Thread／Run 身份、运行状态，可携带 usage。
- `delta`：携带预留 seq 和 message_id 的文本增量，field 表示 content 或 reasoning；当前 Loop 输出 content。
- `event`：已提交完整事实，category 区分 message／lifecycle，payload 保存内容。
- `error`：观察失败；Run 执行失败由 lifecycle 事实表达。

同一 Thread 已有 running 或 interrupted 的 Run 时，请求返回 HTTP 409。
客户端按 seq 排序和合并预览；完整事实到达后覆盖同 seq 预览，重复事实按 seq 去重。
seq 可以有空洞；预留序号不表示完整消息已提交，也不能作为增量续传游标。
EOF 不表示运行成功，完成状态以 lifecycle 事实为准。

客户端断线后只关闭自己的订阅，Agent 继续执行并保存结果。目前不提供实时重连，
也不发送 SSE id 或支持 Last-Event-ID 恢复。通过
`GET /api/threads/{thread_id}/messages` 查询已保存的消息，或使用首帧 run_id 调用
`GET /api/threads/{thread_id}/runs/{run_id}/messages`。不要重发创建请求来恢复观察，
它会新建 Run。服务器关闭时会取消未结束的任务。

帧格式示例（省略中间的完整消息和生命周期事实）：

```text
event: metadata
data: {"thread_id":"thread-1","run_id":"run-1","status":"running"}

event: delta
data: {"seq":3,"message_id":"answer-1","field":"content","value":"你好"}

```

本入口是 POST，浏览器应使用 fetch 流式读取并解析 SSE 帧，不能直接用原生 EventSource
发送请求体。详细契约见 [消息与事件契约](docs/5-message-identity-and-event-contract.md)。
Agent 和 Stream 发布协议无关内部事件，`app/run_contract.py` 负责投影和 SSE 编码。

### 允许容器或局域网访问

如果 Next.js 不在同一网络命名空间中，例如运行在另一个容器、WSL 外部或局域网设备上，使用：

```bash
uv run uvicorn app.server:app \
  --env-file .env \
  --host 0.0.0.0 \
  --port 8000 \
  --reload
```

`0.0.0.0` 是服务器的监听地址。前端请求时应使用宿主机的实际 IP 或域名，不能把 `0.0.0.0` 当作目标地址。

### 完整消息采集

Loop 顺序消费 LangGraph v3 原始事件：`GraphEventAdapter` 将根图 `messages` 转为文本预览、
将根图 `values` 转为完整消息候选。应用 `RunEventIngestor` 负责 seq 预留、持久化和提交后发布。
完整消息不再通过 middleware 保存；Graph 的 checkpoint 恢复职责保持不变。
