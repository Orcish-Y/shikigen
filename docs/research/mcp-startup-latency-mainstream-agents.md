# 主流 Agent 的 MCP 启动延迟处理

> 调研基线：2026-08-12；只引用 OpenClaw、NousResearch Hermes Agent、Anthropic Claude Code 的官方文档、官方 GitHub 仓库源码与官方 issue。各项目迭代很快，本文描述的是调研时 `main` / 当前官方文档所呈现的行为。

## 先说结论

主流实现并没有把“等待所有 MCP Server ready”放在 UI/TUI 启动的关键路径上。它们把三个时刻拆开：

1. **交互界面 ready**：尽快让用户看到输入框并输入。
2. **一次 agent turn 开始**：在这里决定是短暂等待、降级到当前工具快照，还是继续运行并在真正需要 MCP 时等待。
3. **工具目录刷新**：只在安全边界更新模型可见工具，避免一个正在进行的模型请求中途换 schema。

Codex TUI 与用户观察到的行为一致：MCP 启动期间允许用户提交输入，但输入先进入 pending queue；当这一轮 MCP startup settled 后，TUI 才调用 `maybe_send_next_queued_input()` 释放输入。因此它优化的是“可交互时间”，不是让模型在工具集合未稳定时提前执行。[Codex `mcp_startup.rs`](https://github.com/openai/codex/blob/main/codex-rs/tui/src/chatwidget/mcp_startup.rs#L1-L285)

Claude Code 对更进一步的“边连接边执行”描述得最明确：MCP 默认后台连接，只有请求确实需要仍在连接的 Server 时才等待；默认启用 Tool Search 时，这个等待发生在 `ToolSearch` 内，没有 Tool Search 时则通过 `WaitForMcpServers` 工具完成。连接若在 Claude 工作期间完成，工具名会在同一 turn 的下一次模型请求中出现，不必等用户再发一条消息。[Claude Code MCP 官方文档：Tool availability](https://code.claude.com/docs/en/mcp#tool-availability)

Hermes 的做法最接近当前 shikigen-agent 容易落地的版本：后台线程发现 MCP，交互模式在第一次工具快照前最多等 1.5 秒，超时就先用已有工具；慢 Server 完成后，在下一次 turn 的 prologue 原子刷新 agent 的工具快照。单次查询没有“下一轮补上”的机会，因此默认等待上限提高到 15 秒。[Hermes `mcp_startup.py`](https://github.com/NousResearch/hermes-agent/blob/main/hermes_cli/mcp_startup.py#L111-L177)；[Hermes turn 边界刷新](https://github.com/NousResearch/hermes-agent/blob/main/agent/turn_context.py#L447-L473)

OpenClaw 则把 MCP runtime 做成 session-scoped lazy runtime：编辑配置不会连接 Server；配置热应用会销毁缓存 runtime，下一次工具发现/使用才重建；工具目录变化通知会使当前 session 的目录失效，下一次发现/使用再刷新。[OpenClaw MCP 官方文档](https://github.com/openclaw/openclaw/blob/main/docs/cli/mcp.md#openclaw-as-an-mcp-client-registry)；[OpenClaw 配置参考](https://github.com/openclaw/openclaw/blob/main/docs/gateway/configuration-reference.md#mcp)

## 横向对比

| 产品 | UI/TUI 在 MCP 未 ready 时可否接受输入 | agent run / 模型调用是否等待 | 运行时工具更新 | 失败、超时、重连 |
| --- | --- | --- | --- | --- |
| Codex TUI | **可以**。输入在 MCP startup 期间进入 pending queue。 | **等待 startup round settled** 后才释放 queued input 给 agent；源码也有 lag settle 路径，避免无限卡住。 | TUI 接收 app server 的逐 Server 状态更新，并按 startup round 处理迟到事件。 | 每个 Server 显示 `Starting / Ready / Failed / Cancelled`；失败即时 warning，settled 或 lag settle 后释放输入。 |
| Claude Code | **可以**。官方明确说 Server 可在后台连接；请求已经能进入 agent 路径。 | **按需等待**。请求需要仍在连接的 Server 时，等待发生在 `ToolSearch`；禁用 Tool Search 时使用 `WaitForMcpServers`。已缓存远程目录可首条消息立即使用，首次工具调用才连接。 | 支持 MCP `list_changed`，自动刷新 tools/prompts/resources；插件变更可 `/reload-plugins`。 | `MCP_TIMEOUT` 默认 30 秒；HTTP/SSE 断线指数退避 1 秒起、最多 5 次；初连瞬时错误最多 3 次；stdio 不自动重连；可在 `/mcp` 手工 retry/reconnect。 |
| Hermes Agent | **可以启动界面并后台发现**。官方源码专门提供 CLI/TUI-safe background discovery；第一次工具快照只做有界 join。严格说，输入提交后 agent build 仍可能等待这段上限。 | **有界等待后降级**。交互默认最多 1.5 秒；单次查询默认 15 秒。超时后 turn 可先用当前快照，慢工具通常在下一 turn 注入。 | 支持 `notifications/tools/list_changed` 自动刷新；支持 `/reload-mcp`；已有 agent 的工具快照可原子重建，只在 turn 边界发布。还支持 `lazy: true` + schema cache，首次调用才连接。 | 每 Server 默认 connect timeout 60 秒；并行发现，外层 120 秒；首次连接最多 3 次，断线最多 5 次，指数退避/抖动，耗尽后停放并周期自探测；失败 Server 从 registry 移除，不阻塞其他 Server。 |
| OpenClaw | **Gateway / Control UI 不以 MCP 连接为 ready 条件**。配置页本身不启动 transport；MCP runtime 在后续 agent session 的发现/使用路径建立。 | **发现/使用点等待，而非 Gateway 启动等待**。官方资料没有证明它像 Claude Code 那样能让同一个模型 turn 先开始推理、再等待某个连接；更稳妥的表述是它把延迟推迟到首次 discovery/use。 | 支持动态 tool-list：通知使 session catalog 失效，下一次发现/使用刷新；`mcp.*` 配置热应用会 dispose runtime，下一次重建。 | 每 Server 可配置 connect/request timeout；重复 request/protocol 错误会短暂暂停坏 Server；runtime 有默认 10 分钟 idle TTL；显式 `reload` 可释放进程内缓存。官方文档未给出统一的自动重连次数/退避参数。 |

## Claude Code

### 1. UI/TUI 与连接时序

Claude Code 当前官方文档描述了 Server 仍在后台 connecting 时请求已经进入执行路径。对曾经成功使用过的远程 HTTP/SSE Server，v2.1.221 起还能从 discovery cache 直接加载上次的工具目录，状态显示为 `cached … · connects on first use`；工具从第一条消息起可见，真实连接推迟到 Claude 首次调用其工具。[MCP 官方文档：Server status detail](https://code.claude.com/docs/en/mcp#server-status-detail)

因此“用户能先输入”与“模型什么时候能使用 MCP”被明确拆开。这里不能从公开资料精确断言终端输入控件在哪一个内部事件前挂载，但产品契约已经明确：普通 MCP 不阻塞会话启动，连接状态可在 `/mcp` 中看到。

### 2. agent run / 模型调用的等待点

如果请求需要仍在后台连接的 Server，Claude 会等待该 Server：

- 默认开启 Tool Search 时，等待发生在 `ToolSearch` 内。
- Vertex AI、自定义 `ANTHROPIC_BASE_URL` 或 `ENABLE_TOOL_SEARCH=false` 等没有 Tool Search 的配置，通过 `WaitForMcpServers` 工具等待。
- `alwaysLoad` 的 Server 必须在第一次 prompt 中出现，因此在 prompt 构建前等待。
- Server 若在 Claude 工作期间连好，Claude Code 会在**同一 turn 的下一次模型请求**告知工具名，不需要等下一条用户消息。

这比“第一轮一律等完所有 Server”更细：本地工具能够立即工作，只有用到迟到 MCP 的路径才承担等待。[MCP 官方文档：Tool availability](https://code.claude.com/docs/en/mcp#tool-availability)

非交互 `-p` 模式有不同取舍：默认第一条 query 最多等待 5 秒让 `--mcp-config` Server 连接；设置 `MCP_CONNECTION_NONBLOCKING=true` 可完全跳过这次等待，适合脚本根本不需要 MCP 的情况。[Claude Code 环境变量官方文档](https://code.claude.com/docs/en/env-vars#mcp_connection_nonblocking)

### 3. 动态工具集合

Claude Code支持 MCP `list_changed` 通知；Server 的 tools、prompts、resources 变化后，不需要断连重连，客户端会自动刷新能力目录。刷新失败时保留旧目录，直到以后一次刷新成功，而不是瞬间把工具清空。[MCP 官方文档：Dynamic tool updates](https://code.claude.com/docs/en/mcp#dynamic-tool-updates)

工具数量多时，默认 Tool Search 会把 MCP 工具 deferred、按需加载，而不是把所有 schema 塞入首次上下文。`ENABLE_TOOL_SEARCH=false` 才全部 upfront；Server 或单个工具可用 `alwaysLoad` 强制 upfront。[MCP 官方文档：Tool Search](https://code.claude.com/docs/en/mcp#mcp-output-limits-and-warnings)

插件带来的 MCP Server 会随插件启动；会话内启停插件后运行 `/reload-plugins` 连接或断开其 MCP Server。[MCP 官方文档：Plugin-provided MCP servers](https://code.claude.com/docs/en/mcp#plugin-provided-mcp-servers)

### 4. 失败、超时与重连

- `MCP_TIMEOUT` 控制 Server startup timeout，官方环境变量表当前给出的默认值是 30,000 ms。[环境变量官方文档](https://code.claude.com/docs/en/env-vars#mcp_timeout)
- HTTP/SSE 中途断线会自动指数退避重连：最多 5 次，从 1 秒开始翻倍；期间 `/mcp` 显示 pending，耗尽后显示 failed，可手工 retry。[MCP 官方文档：Automatic reconnection](https://code.claude.com/docs/en/mcp#automatic-reconnection)
- 初次启动若遇 5xx、connection refused、timeout 等瞬时错误，v2.1.121 起最多重试 3 次；auth/not-found 不重试。[同上](https://code.claude.com/docs/en/mcp#automatic-reconnection)
- stdio 是本地子进程，官方明确说不会自动重连；通过 `/mcp` 手工重连。[同上](https://code.claude.com/docs/en/mcp#automatic-reconnection)

## Hermes Agent

### 1. UI/TUI 与后台发现

Hermes 把 MCP SDK import 和网络发现移出了 `model_tools` 的模块级 side effect。源码注释记录了原因：Gateway 会在 asyncio event loop 中 lazy-import 该模块；若导入时同步发现，慢或不可达 Server 可冻结 Discord/Telegram heartbeat 最多 120 秒。现在每个 entry point 自己安排发现，Gateway 放到 executor，ACP 用 `asyncio.to_thread`，CLI/TUI 走专门启动路径。[Hermes `model_tools.py`](https://github.com/NousResearch/hermes-agent/blob/main/model_tools.py#L188-L204)

`start_background_mcp_discovery()` 启动 daemon thread，显式目标就是 CLI/TUI-safe background discovery；没有配置 MCP 时还会用便宜的 config probe 避免 import MCP stack。[Hermes `mcp_startup.py`](https://github.com/NousResearch/hermes-agent/blob/main/hermes_cli/mcp_startup.py#L13-L109)

TUI entry 的顺序也能直接验证“先显示输入、后台继续连接”：`main()` 先启动 discovery thread，随即发送 `gateway.ready`，再进入读取 stdin 的 loop；源码注释明确说这样避免死 Server 的 1+2+4 秒重试让 composer 出现前产生约 7 秒空白。[Hermes `tui_gateway/entry.py`](https://github.com/NousResearch/hermes-agent/blob/main/tui_gateway/entry.py#L384-L420)

首次工具快照前并非完全不等，而是 `thread.join(bound)`：交互默认 1.5 秒，单次 query 默认 15 秒。连接快则立即返回；连接慢则到上限后继续启动。[Hermes `mcp_startup.py`](https://github.com/NousResearch/hermes-agent/blob/main/hermes_cli/mcp_startup.py#L111-L177)

### 2. agent run / 模型调用的等待点

Hermes 的 `AIAgent` 构造时会 snapshot 工具，因此它在 agent build 前给后台发现一个短暂窗口。超过窗口仍未 ready 的工具不会出现在第一 turn 中；这不是在同一 turn 内继续等，而是先用当前快照运行，再在安全边界补上。

官方源码对这个权衡写得很清楚：交互会话有后续 turn，可依靠 between-turns late binding；单次 query 没有第二轮，所以等待上限更长。[Hermes `mcp_startup.py`](https://github.com/NousResearch/hermes-agent/blob/main/hermes_cli/mcp_startup.py#L111-L146)

此外，Hermes 现在支持 Server 级 `lazy: true`。若 config fingerprint 命中有效 schema cache，启动时直接从磁盘 cache 注册 schema，不 spawn/连接 Server，第一次真实工具调用才连接；cache 缺失或过期才回退到 eager connect。[Hermes `mcp_tool.py`](https://github.com/NousResearch/hermes-agent/blob/main/tools/mcp_tool.py#L6220-L6319)

### 3. 动态工具集合

Hermes 支持两类刷新：

- MCP Server 发 `notifications/tools/list_changed`，后台重新 `list_tools`，加锁防止重叠刷新，并更新全局 registry。[Hermes MCP 官方指南](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/mcp.md#dynamic-tool-discovery)
- 用户修改配置后执行 `/reload-mcp`，重载 Server 和工具列表。[Hermes MCP 官方指南](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/mcp.md#reloading)

仅更新全局 registry 不够，因为 agent 已经 snapshot。`refresh_agent_mcp_tools()` 会重新推导 `agent.tools` / `valid_tool_names`，通过 generation guard 拒绝旧快照覆盖新快照，并在同一锁中原子发布。注释明确要求 late binding 只发生在 turn boundary、下一次 `tools=` request prefix 生成之前。[Hermes `mcp_tool.py`](https://github.com/NousResearch/hermes-agent/blob/main/tools/mcp_tool.py#L6647-L6782)；[Hermes `turn_context.py`](https://github.com/NousResearch/hermes-agent/blob/main/agent/turn_context.py#L447-L473)

### 4. 失败、超时与重连

Hermes 当前实现的默认值与策略包括：

- 每 Server 初连 timeout 默认 60 秒，工具调用 timeout 默认 300 秒。
- 多 Server 并行发现；外层 discovery 总等待上限 120 秒；单 Server 异常以 `gather(return_exceptions=True)` 隔离。
- 第一次连接最多重试 3 次；已连接后的断线最多重连 5 次；退避上限 60 秒并带 ±20% jitter。
- 重连预算耗尽后 Server 进入 parked，工具从 registry 移除；默认每 300 秒做一次自恢复 probe。
- HTTP/SSE 有 keepalive；默认 180 秒，配置下限 5 秒。

这些常量与意图见 [Hermes `mcp_tool.py` 连接常量](https://github.com/NousResearch/hermes-agent/blob/main/tools/mcp_tool.py#L394-L427)，并行发现与外层超时见 [同文件 discovery](https://github.com/NousResearch/hermes-agent/blob/main/tools/mcp_tool.py#L6321-L6412)。

需要注意：Hermes 的方案经历过真实 race。官方 issue 曾记录 0.75 秒窗口太短导致 MCP 已连接却未进入 agent snapshot；后续实现增加等待并加入 late-binding refresh。这个案例恰好说明：**后台加载本身不够，必须同时设计“已构造 agent 如何看到迟到工具”的刷新边界。** [Hermes 官方 issue #41625](https://github.com/NousResearch/hermes-agent/issues/41625)

## OpenClaw

### 1. UI / Gateway 与 MCP lifecycle

OpenClaw 的 MCP 配置管理面和 runtime 连接面是分离的：`list`、`show`、`status`、普通 `doctor`、`set`、`configure`、`tools`、`reload`、`unset` 都不连接目标 Server；只有 `probe` / `doctor --probe` 做 live connection proof。浏览器 Control UI 的 MCP 页面也只是配置与 inventory 页面，本身不启动 transport。[OpenClaw MCP 官方文档](https://github.com/openclaw/openclaw/blob/main/docs/cli/mcp.md#openclaw-as-an-mcp-client-registry)

因此 Gateway / Control UI 可以先 ready 并接收操作，MCP 连接延迟不会成为配置 UI 的启动 barrier。对于聊天消息，嵌入式 runtime 在 agent session 的工具 discovery/use 路径才取得 MCP runtime。

### 2. agent run / 模型调用的等待点

OpenClaw 的官方资料明确证明的是“延迟发生在首次 discovery/use，而不是 Gateway boot”：session-scoped runtime 会缓存，idle 后回收；配置变化使缓存失效，下一次工具发现/使用重建。[OpenClaw 配置参考](https://github.com/openclaw/openclaw/blob/main/docs/gateway/configuration-reference.md#mcp)

没有足够第一方证据证明 OpenClaw 像 Claude Code 一样，在同一个模型 turn 中先让模型用本地工具开始推理，再通过一个显式 wait tool 等待 MCP。因此对 OpenClaw 最安全的结论是：**它避免全局启动等待，但首次需要构造 MCP 工具目录的 agent run 仍会承担发现延迟。**

### 3. 动态工具集合

- Server 的动态 tool-list change 会 invalidate 当前 session 的 cached catalog；下一次 discovery/use 刷新。
- `mcp.*` 配置 hot-apply 会 dispose cached session runtimes；下一次 discovery/use 按新配置重建，移除的 Server 立即被回收。
- `openclaw mcp reload` 显式释放当前进程的 MCP runtime cache；由其他进程持有的 runtime 仍需对应进程自己的 reload/restart。

依据：[OpenClaw MCP 官方文档](https://github.com/openclaw/openclaw/blob/main/docs/cli/mcp.md#openclaw-as-an-mcp-client-registry)；[OpenClaw 配置参考](https://github.com/openclaw/openclaw/blob/main/docs/gateway/configuration-reference.md#mcp)。

### 4. 失败、超时与重连

OpenClaw 每 Server 支持 `connectTimeout` / `connectionTimeoutMs` 与 `timeout` / `requestTimeoutMs`。重复 MCP request/protocol 失败会短暂暂停该 Server，避免一个坏 Server 吃掉整轮 agent turn。session runtime 默认 idle TTL 为 10 分钟；one-shot embedded run 在 run 结束释放它打开的 runtime，避免累积 stdio 子进程。[OpenClaw MCP 官方文档](https://github.com/openclaw/openclaw/blob/main/docs/cli/mcp.md#openclaw-as-an-mcp-client-registry)

官方当前文档没有公布统一的“初连重试 N 次 / 指数退避参数”，所以不能把 Claude Code 或 Hermes 的次数套到 OpenClaw。它公开保证的是 timeout、短暂暂停坏 Server、lazy recreate、显式 reload 与生命周期清理。

## 对 shikigen-agent 的建议

用户想要的体验可以拆成两个版本。

### 版本 A：现在最值得做

目标是“程序一启动就能输入；用户提交后，若 MCP 仍在加载，则等它完成再真正启动 agent turn”。

建议时序：

```text
main
  ├─ 同步创建 builtin registry
  ├─ 立即启动 MCP discovery task
  └─ 立即进入 interactive input loop

用户输入完成
  ├─ 若 discovery 已完成：直接合并工具
  ├─ 若仍进行中：界面显示「正在连接 MCP…」，await task
  ├─ 生成这一 turn 的 immutable tool snapshot
  └─ create/invoke agent
```

这不会缩短“冷启动后的第一轮总耗时”，但会把用户阅读 banner、思考和输入 prompt 的时间与 MCP I/O 重叠，明显改善体感；如果用户输入较慢，连接通常早已完成。

这里有三个必须锁住的架构边界：

1. **输入 loop 不依赖 MCP ready。** composition root 持有 discovery task / readiness，不让 registry factory 再变 async。
2. **每个 turn 使用稳定工具快照。** 不要在一次 LLM 请求进行中直接 mutate 已 bind 的工具；只在 invoke 前或两个 turn 之间更新。
3. **失败是完成态，不是永远 pending。** discovery result 应同时包含 `ready tools` 和 `failed servers/diagnostics`；否则输入提交后可能无限等。

### 版本 B：以后工具多了再做

借鉴 Claude Code，增加一个稳定的 `tool_search` / `wait_for_mcp_servers` 能力：第一次模型调用只带 builtin + tool catalog/search，不必等所有 Server；模型确实需要某个 MCP 时才等待和 materialize schema。这能真正减少不需要 MCP 的 first-token latency，但复杂度明显更高，涉及 deferred tool schema、server readiness、模型重试与 prompt-cache 一致性。

Hermes 的 `lazy: true` + schema cache 是中间路线：缓存上一次成功发现的 schema，启动时立即把 schema 注册给模型，首次调用才连接。它改善首 token，但必须处理 schema 已过期、工具调用时连接失败、Server 删除工具等一致性问题，不适合当前第一版直接照搬。

### 推荐的语义选择

当前项目建议先采用：

- UI/TUI：立即 ready。
- MCP discovery：后台并发、逐 Server 隔离。
- 第一 turn：默认等待 discovery 完成，但配置一个总上限；达到上限后明确询问/提示“以本地工具继续”，不要静默丢 MCP。
- 后续 turn：如果超时 Server 后来成功，只在 turn boundary 更新 registry 并重建 agent/tool binding。
- 状态：至少表达 `configured / connecting / ready / failed / timed_out`，而不是只有一份工具 list。
- reload：更新配置后取消/释放旧连接，在下一安全边界重新发现。

这个选择比直接复制 Claude Code 更符合当前规模：先解决“可输入”和“异步 I/O 不污染 factory”，等有大量 MCP 工具和 prompt token 压力时，再引入 Tool Search。

## 仍不确定的点

1. Claude Code 是闭源核心实现；官方文档给出了产品契约，但公开仓库无法验证 TUI component mount 与 MCP task 创建的具体代码顺序。
2. OpenClaw 当前 MCP 客户端能力更新很快。官方文档能确认 lazy session runtime、cache invalidation 和 failure pause，但没有公开统一的重连次数/退避参数，也没有明确承诺“同一 turn 内先模型调用、后等待 MCP”。
3. Hermes `main` 已加入 background discovery、bounded wait、late binding 和 lazy schema cache；旧 release / issue 中描述的 0.75 秒窗口或 TUI 子进程缺工具问题不代表当前 `main`，这里只把它们当作架构失败案例。
