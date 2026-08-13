# Shikigen Agent

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
uv run uvicorn harness.server:app \
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

`curl -N` 会关闭输出缓冲，使 SSE 事件到达后立即显示。

### 允许容器或局域网访问

如果 Next.js 不在同一网络命名空间中，例如运行在另一个容器、WSL 外部或局域网设备上，使用：

```bash
uv run uvicorn harness.server:app \
  --env-file .env \
  --host 0.0.0.0 \
  --port 8000 \
  --reload
```

`0.0.0.0` 是服务器的监听地址。前端请求时应使用宿主机的实际 IP 或域名，不能把 `0.0.0.0` 当作目标地址。
