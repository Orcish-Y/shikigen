# DeerFlow MCP 配置读取机制

> 调研基线：ByteDance 官方 `bytedance/deer-flow` 仓库 `main` 分支与官方文档，核对日期 2026-08-11。本文讨论当前 DeerFlow 2.x；源码仍保留若干旧名称兼容逻辑。

## 结论

DeerFlow 当前不从通用的 `config.json` 读取 MCP。它把应用配置放在 `config.yaml`，把 MCP Server、Skill 开关及 MCP interceptor 等运行时扩展配置放在项目根目录的 `extensions_config.json`。官方推荐复制 `extensions_config.example.json` 后修改；`mcp_config.json` 仅是路径解析时保留的旧文件名兼容。[官方 MCP 指南](https://github.com/bytedance/deer-flow/blob/main/backend/docs/MCP_SERVER.md#setup)；[路径解析源码](https://github.com/bytedance/deer-flow/blob/main/backend/packages/harness/deerflow/config/extensions_config.py#L161-L227)

其核心做法可以概括为：

1. 用 Pydantic 模型表达配置，而不是把任意 JSON 字典直接传给 Agent。
2. 加载时递归解析完整字符串形式的 `$ENV_VAR`，然后做模型校验。
3. 仅选择 `enabled: true` 的 Server，转换为 `langchain-mcp-adapters` 的连接配置。
4. 各 Server 并行发现工具，单个 Server 失败或超时只跳过该 Server。
5. 工具结果缓存；每次取缓存时用“解析后的配置路径 + `(mtime, size, sha256)`”判断是否应重建。
6. `stdio` 使用按用户/线程隔离的持久 Session；HTTP/SSE 工具不进入 Session Pool。

对于本项目，值得借鉴的是“独立配置模型 + 每次重建前重新读盘 + 内容签名热重载”，不必照搬 DeerFlow 的 Gateway API、OAuth、文件路径改写和复杂 Session Pool，除非本项目也需要 Web 管理、多用户及有状态 MCP（例如 Playwright）。

## 配置文件与格式

官方示例的顶层结构如下；公开文件形状使用驼峰键 `mcpServers`，而 Python 模型字段为 `mcp_servers`，通过 Pydantic alias 对接。[官方示例](https://github.com/bytedance/deer-flow/blob/main/extensions_config.example.json)；[ExtensionsConfig 模型](https://github.com/bytedance/deer-flow/blob/main/backend/packages/harness/deerflow/config/extensions_config.py#L140-L158)

```json
{
  "middlewares": [],
  "mcpInterceptors": [],
  "mcpServers": {
    "github": {
      "enabled": true,
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {
        "GITHUB_TOKEN": "$GITHUB_TOKEN"
      },
      "tool_name_prefix": true,
      "session_init_timeout": 60,
      "tool_call_timeout": 60,
      "description": "GitHub MCP server for repository operations"
    }
  },
  "skills": {}
}
```

`McpServerConfig` 的主要字段是：

- 通用：`enabled`、`type`、`description`。
- `stdio`：`command`、`args`、`env`。
- `http` / `sse`：`url`、`headers`、可选 `oauth`。
- 工具行为：`tool_name_prefix`（默认 `true`）、`session_init_timeout`（当前默认 60 秒）、`tool_call_timeout`（只对 stdio 生效）。
- 软路由：Server 级 `routing`，以及 `tools.<original_tool_name>.routing` 覆盖。

模型允许 `type` 使用 MCP 规范中的别名 `transport`；二者同时存在时 `type` 优先。Server 模型允许额外字段，以便向 adapter 兼容扩展；而 `routing` 自身禁止未知字段。[Server 配置模型](https://github.com/bytedance/deer-flow/blob/main/backend/packages/harness/deerflow/config/extensions_config.py#L81-L122)；[路由模型](https://github.com/bytedance/deer-flow/blob/main/backend/packages/harness/deerflow/config/extensions_config.py#L27-L57)

三种传输最终被严格归一为：

- `stdio` 必须有 `command`，可传 `args` / `env`。
- `http` 或 `sse` 必须有 `url`，可传 `headers`。
- 其他 `type` 会报“不支持”；但转换多个 Server 时，错误 Server 只会被记录并略过。[连接参数转换源码](https://github.com/bytedance/deer-flow/blob/main/backend/packages/harness/deerflow/mcp/client.py#L10-L63)

## 文件路径解析

`ExtensionsConfig.resolve_config_path()` 的优先级是：

1. 显式传入的 `config_path`。
2. 环境变量 `DEER_FLOW_EXTENSIONS_CONFIG_PATH`。
3. 调用方项目根目录下的 `extensions_config.json`，再尝试旧名 `mcp_config.json`。
4. 为 monorepo / 旧部署兼容，再搜索 backend 目录和仓库根目录下的上述两个文件名。
5. 只有“自动搜索模式”全都找不到时，才返回 `None`，把扩展配置视为可选。

显式参数或环境变量指定的文件不存在会抛 `FileNotFoundError`，因为这代表操作员明确声明了一个必须存在的配置；不会静默退化成“无 MCP”。[路径解析实现](https://github.com/bytedance/deer-flow/blob/main/backend/packages/harness/deerflow/config/extensions_config.py#L161-L227)

这比直接写 `Path("config.json")` 更适合可部署 Agent：本地开发可约定项目根目录，Docker/生产环境则能显式挂载并通过环境变量指定路径。

## 解析与验证

`ExtensionsConfig.from_file()` 的顺序是：

1. 解析实际路径。
2. 没找到可选配置时，返回 `mcp_servers={}`、`skills={}` 的空模型。
3. 用 UTF-8 和 `json.load()` 读取。
4. 递归遍历字典、列表、元组；只有“整个字符串以 `$` 开头”的值才按环境变量名替换。变量不存在时替换成空字符串，而不是把 `$VAR` 原样传下去。
5. 用 `ExtensionsConfig.model_validate()` 验证并生成类型化对象。

非法 JSON 被包装为包含文件路径的 `ValueError`；其他读取或模型验证异常被包装为包含文件路径的 `RuntimeError`。[读取与环境变量解析](https://github.com/bytedance/deer-flow/blob/main/backend/packages/harness/deerflow/config/extensions_config.py#L229-L290)

需要注意两点：

- 这种替换不支持 `"Bearer $TOKEN"` 形式的字符串插值；应该把整个值写成 `$TOKEN`，或通过 interceptor 动态构造请求头。
- 缺失变量变成空字符串，Pydantic 类型验证不会自动认为它是“缺少凭证”；连接初始化通常会失败，DeerFlow 随后跳过该 Server。官方 OpenViking 说明也明确指出，修改环境变量本身不会改变配置文件签名，因此要重启、重新保存配置或调用 cache-reset。[官方 MCP 指南](https://github.com/bytedance/deer-flow/blob/main/backend/docs/MCP_SERVER.md#openviking-mcp-tools)

`ExtensionsConfig`、`McpServerConfig` 与 OAuth 模型对额外字段总体采用 `extra="allow"`，所以它偏向前向兼容，并不是严格 JSON Schema 白名单。真正依赖传输类型的必填检查是在转换为 adapter 参数时完成，而不是全部在 Pydantic 模型阶段完成。[配置模型](https://github.com/bytedance/deer-flow/blob/main/backend/packages/harness/deerflow/config/extensions_config.py#L60-L158)；[连接参数转换](https://github.com/bytedance/deer-flow/blob/main/backend/packages/harness/deerflow/mcp/client.py#L10-L63)

## 工具加载与生命周期

`get_mcp_tools()` 不读取缓存的全局 `ExtensionsConfig`，而是每次真正初始化工具时调用 `ExtensionsConfig.from_file()`，确保另一进程或 Gateway API 落盘的配置能被看到。之后：

1. 筛出启用的 Server，并构造 `MultiServerMCPClient` 配置。
2. 为 HTTP/SSE 注入 OAuth 初始 Header；支持 `client_credentials` 与 `refresh_token`，并可安装自动刷新 interceptor。
3. 加载 `mcpInterceptors` 中的 `module:builder`。解析失败、builder 报错或返回非 callable 时记录 warning 并跳过，不阻断其他 interceptor。
4. 按 Server 并行发现工具。每个 Server 单独受 `session_init_timeout` 约束；失败或超时返回空列表，所以其他 Server 仍可工作。
5. 默认把工具名变成 `<server_name>_<tool_name>` 防止冲突。外部 Server 给出的工具名若不匹配 `^[A-Za-z0-9_-]+$` 会被丢弃，避免它在 deferred-tool prompt 中伪造结构。
6. `stdio` 工具被包装成持久 Session 调用；HTTP/SSE 保留 adapter 原工具。

以上行为可见于 [工具加载主流程](https://github.com/bytedance/deer-flow/blob/main/backend/packages/harness/deerflow/mcp/tools.py#L565-L754) 和 [官方 MCP 指南](https://github.com/bytedance/deer-flow/blob/main/backend/docs/MCP_SERVER.md#custom-tool-interceptors)。

`stdio` 的持久 Session 以 `(server_name, scope_key)` 建池，实际 scope 通常包含用户和线程，因此同一线程中的连续调用可以共享浏览器页面等 Server 状态，而不会把不同用户/线程混在一起。Session 由专属 async task 负责进入和退出 context manager，并在池容量达到上限时 LRU 淘汰；这是为了解决 AnyIO cancel scope 必须在同一 task 退出的问题。[Session Pool 源码](https://github.com/bytedance/deer-flow/blob/main/backend/packages/harness/deerflow/mcp/session_pool.py)

HTTP/SSE 不进入池，因为 adapter 内部 AnyIO TaskGroup 若跨 task 清理会报错。`stdio` 的每次工具调用还可使用 `tool_call_timeout`；HTTP/SSE 应使用 transport 层超时。[工具包装逻辑](https://github.com/bytedance/deer-flow/blob/main/backend/packages/harness/deerflow/mcp/tools.py#L688-L750)；[超时说明](https://github.com/bytedance/deer-flow/blob/main/backend/docs/MCP_SERVER.md#server-timeouts-stdio-mcp-servers)

当 `config.yaml -> tool_search.enabled` 开启时，MCP 工具不会把完整 schema 全部绑定进模型上下文，而是先只列工具名，由内置 `tool_search` 按需加载；路由提示还可自动提升匹配的 deferred schema。这是工具数量较多时的上下文优化，不属于配置文件读取本身。[官方 MCP 集成文档](https://deerflow.tech/en/docs/harness/mcp)

## 缓存与热重载

工具缓存是进程级全局缓存，并由 async lock 保证初始化串行：首次 `get_cached_mcp_tools()` 才加载，即 lazy initialization。[缓存初始化源码](https://github.com/bytedance/deer-flow/blob/main/backend/packages/harness/deerflow/mcp/cache.py#L105-L171)

每次读取缓存时会重新解析配置路径并计算 `(mtime, size, sha256)` 内容签名；只要路径或签名不同，就清空工具缓存和 Session Pool，下次使用重新读取配置、发现工具。因此正常编辑或原子替换 `extensions_config.json` 不需要重启。[缓存失效源码](https://github.com/bytedance/deer-flow/blob/main/backend/packages/harness/deerflow/mcp/cache.py#L13-L102)

有一个刻意的 fail-soft 边界：已经成功加载后，如果配置文件被删除或暂时不可读，当前签名为 `None`，缓存不会失效，而是继续提供“最后一次成功加载”的工具。显式路径在真正重新加载时依然会大声报错；只是高频缓存陈旧检查不让临时挂载故障击穿每个请求。[缓存失效说明](https://github.com/bytedance/deer-flow/blob/main/backend/packages/harness/deerflow/mcp/cache.py#L28-L100)

Gateway 的 `PUT /api/mcp/config` 和 `PATCH /api/mcp/config` 会在原子写盘并刷新配置 singleton 后，显式 reset 工具缓存；`POST /api/mcp/cache/reset` 也可手动清空缓存和所有持久 Session。reset 只影响当前 Gateway 进程，下一次 Agent run 或工具查询才懒加载新工具。[Gateway MCP API](https://github.com/bytedance/deer-flow/blob/main/backend/app/gateway/routers/mcp.py#L807-L899)

写盘使用同目录临时文件、`flush + fsync`、`os.replace` 和目录 fsync，并尽量保留原文件 mode 与 symlink target；共享的 `threading.Lock` 包住 read-modify-write，避免 MCP 与 Skill 两类更新互相覆盖。[原子写盘与锁](https://github.com/bytedance/deer-flow/blob/main/backend/packages/harness/deerflow/config/extensions_config.py#L315-L419)

## 错误处理策略

DeerFlow 的错误策略分层明显：

| 层级 | 行为 |
| --- | --- |
| 配置路径 | 显式路径缺失 fail-fast；自动搜索无文件返回空配置 |
| JSON / Pydantic | 整份文件错误，抛带路径的异常 |
| Server 参数转换 | 缺 `command` / `url` 或 transport 不支持，仅记录并跳过该 Server |
| 工具发现 | 每个 Server 独立 timeout / catch，坏 Server 不影响健康 Server |
| interceptor | 单项加载失败记录 warning 并跳过 |
| 总体 MCP 初始化 | adapter 缺失时 warning 后返回空工具；外层意外异常记录 error 后返回空工具 |
| lazy cache 调用 | 初始化异常记录 exception 后返回空工具，不阻断 Agent 构造 |
| 配置删除 | 已有工具缓存继续提供 last-known-good |

依据：[配置读取](https://github.com/bytedance/deer-flow/blob/main/backend/packages/harness/deerflow/config/extensions_config.py#L229-L290)、[Server 转换](https://github.com/bytedance/deer-flow/blob/main/backend/packages/harness/deerflow/mcp/client.py#L10-L63)、[工具加载](https://github.com/bytedance/deer-flow/blob/main/backend/packages/harness/deerflow/mcp/tools.py#L565-L754)、[缓存读取](https://github.com/bytedance/deer-flow/blob/main/backend/packages/harness/deerflow/mcp/cache.py#L129-L171)。

这个取舍让 MCP 是可选增强，而不是 Agent 的单点故障。不过它也意味着“Agent 能启动”不代表 MCP 配置正确；实现时必须有清晰日志，并最好提供启动诊断或列出实际加载到的 Server/工具。

## 安全含义

1. **配置文件是受信任的代码执行边界。** `stdio.command` 能启动本地进程，`npx` / `uvx` 本身也能下载并执行包；`mcpInterceptors` 还能动态 import Python builder。因此不能允许普通用户编辑此文件，也不应把未审查的 MCP Server 当作纯数据插件。
2. **Gateway 写接口必须强鉴权。** DeerFlow 的 MCP GET/PUT/PATCH/reset 都要求 admin。API 注册的 stdio 默认只允许裸可执行名 `npx` / `uvx`，拒绝路径、空白和 shell 元字符，并屏蔽可把 launcher 变成任意代码 evaluator 的参数与启动时注入代码的环境变量；官方源码也明确说明这是 defense-in-depth，不是完整信任边界。[Gateway 校验源码](https://github.com/bytedance/deer-flow/blob/main/backend/app/gateway/routers/mcp.py#L29-L43)；[请求校验](https://github.com/bytedance/deer-flow/blob/main/backend/app/gateway/routers/mcp.py#L550-L583)
3. **手工配置不受上述 API allowlist 限制。** 这是有意设计：本地操作员可表达高级部署，但意味着文件权限、代码审查和部署边界必须承担安全责任。
4. **密钥用环境变量占位，而不是把值提交进 JSON。** Gateway GET 会遮蔽所有 env/header 值，并移除 OAuth client secret / refresh token；PUT round-trip 会把 `***` 合并回磁盘上的原值，防止 UI 开关 Server 时覆盖秘密。[密钥遮蔽与保留](https://github.com/bytedance/deer-flow/blob/main/backend/app/gateway/routers/mcp.py#L585-L683)
5. **请求级用户凭证应走 `config.context.secrets` interceptor。** 不应放在 metadata；官方说明该 carrier 在 live interceptor 可见，但会从持久化/API 可见配置中移除。[官方 interceptor 指南](https://github.com/bytedance/deer-flow/blob/main/backend/docs/MCP_SERVER.md#custom-tool-interceptors)
6. **远端 MCP 返回内容不天然可信。** DeerFlow 至少约束了工具名，避免 deferred prompt 结构注入；工具输出本身仍需依 Agent 的 guardrail / output sanitization 策略处理。[工具名校验](https://github.com/bytedance/deer-flow/blob/main/backend/packages/harness/deerflow/mcp/tools.py#L27-L36)
7. **有破坏性的远端工具需要显式策略。** 例如官方文档说明 OpenViking 的 `forget` 会永久删除资源，而 DeerFlow 不自动强制二次确认，操作员应通过 denied-tools 等 guardrail 禁用或约束。[官方 OpenViking 安全说明](https://github.com/bytedance/deer-flow/blob/main/backend/docs/MCP_SERVER.md#openviking-mcp-tools)
8. **不要重复接 Filesystem MCP。** DeerFlow 官方明确建议对自身 workspace 使用内置文件工具，因为 MCP Roots 尚未适配，多套路径语义会造成不稳定和越界理解风险。[官方 Filesystem MCP 说明](https://github.com/bytedance/deer-flow/blob/main/backend/docs/MCP_SERVER.md#filesystem-mcp-servers)

## 对 shikigen-agent 的建议

如果目标只是让当前 CLI Agent 从 JSON 连接 GitHub MCP，建议采用 DeerFlow 的简化版：

- 文件名用 `mcp_config.json` 或 `extensions_config.json`，不要占用含义模糊的 `config.json`；如果项目未来有 models、sandbox 等总配置，可以再采用 DeerFlow 的“双配置文件”分层。
- 建立 `McpServerConfig` / `McpConfig` Pydantic 模型，公开格式使用 `mcpServers`，内部字段可用 `mcp_servers`。
- 路径优先级建议为：显式函数参数 → `SHIKIGEN_MCP_CONFIG_PATH` → 项目根目录默认文件。显式路径缺失 fail-fast，默认文件缺失则返回空配置。
- 先只支持项目实际需要的 `http` 与 `stdio`；每种 transport 做 discriminated validation，最好在模型阶段就校验 `command` / `url`，比 DeerFlow 的后置转换更早暴露错误。
- `$VAR` 仅支持整值替换；缺失变量建议直接报出“哪个 Server 的哪个变量缺失”，不要静默变空字符串。对个人 CLI 来说，可诊断性比 DeerFlow 多租户服务的 fail-soft 更重要。
- 并行加载各 Server，并隔离单 Server 失败；记录“启用 Server 数、成功 Server 数、工具名”。
- 第一版若每次进程只运行一个交互会话，可以在应用生命周期内持有一个 `MultiServerMCPClient`，暂不实现文件签名热重载。需要运行时编辑时，再加入 path + SHA-256 签名与显式 reload。
- GitHub 远程 HTTP MCP 不需要 stdio Session Pool；只有接入 Playwright 等有状态 stdio Server 时，才值得引入线程/用户 scope 的持久 Session。
- 配置与 token 分离；GitHub token 只放环境变量。默认只读、最小权限，并对可写 GitHub 工具做 allowlist 或用户确认。

最重要的设计判断是：**读取 JSON 很简单，真正应复制的是配置的信任边界、验证时机、单 Server 故障隔离和可观察性。**
