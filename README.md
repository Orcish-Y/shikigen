# Shikigen Agent

## 项目结构

- `packages/harness/shikigen/`：框架包，包含 Agent、执行 Loop、运行时、工具和 middleware，使用 `shikigen.*` 导入。
- `app/`：应用层，包含 FastAPI 服务器，依赖 `shikigen`。
- `app/routes/thread.py`：会话列表、创建会话、会话历史消息。
- `app/routes/run.py`：发起流式运行、查询运行消息；SSE 事件编码位于 `app/run_contract.py`。
- `app/persistence/`：会话与运行数据库、SQLite checkpoint 连接管理。
- `app/runtime.py`：HTTP 请求共享的应用运行时。
- `tests/`：测试。

根项目通过 uv workspace 依赖 `shikigen-harness`；`uv sync` 会以 editable 模式安装框架包。
以下命令均在项目根目录执行；默认配置 `config.json` 和运行数据路径相对于当前工作目录。

## 运行测试

```bash
uv run python -m unittest discover -s tests
```

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
- `delta`：按 message_id 关联的文本增量，field 表示 content 或 reasoning；当前 Loop 输出 content。
- `event`：已提交完整事实，category 区分 message／lifecycle，payload 保存内容。
- `error`：观察失败；Run 执行失败由 lifecycle 事实表达。

同一 Thread 已有 running 或 interrupted 的 Run 时，请求返回 HTTP 409。
客户端按稳定消息身份合并预览；完整事实到达后覆盖预览，按 seq 去重。
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
data: {"message_id":"answer-1","field":"content","value":"你好"}

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
