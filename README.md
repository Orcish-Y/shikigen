# Shikigen Agent

## 项目结构

- `packages/harness/shikigen/`：框架包，包含 Agent、执行 Loop、运行时、工具和 middleware，使用 `shikigen.*` 导入。
- `app/`：应用层，包含 FastAPI 服务器，依赖 `shikigen`。
- `app/routes/thread.py`：会话列表、创建会话、会话历史消息。
- `app/routes/run.py`：发起流式运行、查询运行消息和 JSONL 事件编码。
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

复制响应中的 `thread_id`，然后发送一条消息并消费 JSONL 事件流：

```bash
curl -N \
  -X POST http://127.0.0.1:8000/api/threads/<thread_id>/stream \
  -H "Content-Type: application/json" \
  -d '{"message":"你好，请介绍一下自己"}'
```

`curl -N` 会关闭输出缓冲，使每一行 JSON 事件到达后立即显示。模型回答以
`message.delta` 事件逐段返回；同一个输出项的事件共享 `output_index`，客户端可据此
将事件归并成最终数组。

同一 thread 已有 pending 或 running 的 run 时，请求返回 HTTP 409。
正常结束发送 `run.completed`，取消发送 `run.cancelled`，失败发送 `run.error`。

客户端断线后只关闭该连接的流式订阅，Agent 和 run 继续执行并保存结果，
后台任务结束后自动回收内存中的 run 和事件流。目前不提供实时断线重连；
可通过 `GET /api/threads/{thread_id}/messages` 查询已保存的消息，
或使用 metadata 中的 run_id 调用 `GET /api/threads/{thread_id}/runs/{run_id}/messages`。
服务器关闭时仍会取消未结束的任务。

```jsonl
{"id":"0","event":"metadata","data":{"run_id":"abc"}}
{"id":"1","event":"message.delta","data":{"delta":"你"},"output_index":0}
{"id":"2","event":"message.delta","data":{"delta":"好"},"output_index":0}
{"id":"3","event":"message.completed","data":{},"output_index":0}
{"id":"4","event":"run.completed","data":{"status":"completed"}}
```

Agent 和 Stream 内部只发布与传输格式无关的通用事件；JSONL 事件名称转换、
`output_index` 分配和逐行编码集中在 Server 的传输 adapter 中完成。

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
