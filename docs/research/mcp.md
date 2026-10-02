# MCP 配置、工具发现与启动延迟

合并 DeerFlow 配置读取、空值处理、主流 Agent 启动延迟三份调查；基线日期 2026-08-11～12。以下是历史调查摘要，本次未更新上游版本；详细配置字段、源码与时序证据见 [归档](../archive/README.md)。

## 配置读取保留的结论

DeerFlow 的应用配置与扩展配置分开：`config.yaml` 与 `extensions_config.json`；公开字段 `mcpServers` 映射到 Python `mcp_servers`。模型校验、环境变量解析、enabled 过滤、工具发现与缓存各有明确边界。

| 输入或情形 | 原调查所见 |
| --- | --- |
| 缺少 `mcpServers` | 默认为空 dict |
| `mcpServers: {}` | 合法空集合 |
| `mcpServers: null` | 校验失败，不自动转为空 dict |
| 自动搜索未找到扩展配置 | 构造空配置 |
| 显式路径指向不存在文件 | 报错，不静默回退 |

文件加载与 Gateway API 的兼容行为不可直接互推。环境变量先解析再校验；并行发现单 Server 失败可隔离；缓存失效依据配置路径和内容签名。stdio 持久 Session Pool 与 HTTP/SSE 工具的连接生命周期不同。配置细节不是本项目必须照搬的范围，当前 schema 以 `AppConfig` 为准。

## 启动有三个独立时刻

1. UI/TUI 可以接收输入。
2. MCP 已连接并拿到目录。
3. 本轮模型调用获得稳定工具快照。

先显示界面、后台发现工具可以把输入思考时间与 I/O 重叠，但不保证首次需要 MCP 的模型调用更快。若要降低无需 MCP 的 first-token latency，还要延迟发现/加载或设计 tool search。

| 样本 | 原调查的等待位置 | 工具更新边界 |
| --- | --- | --- |
| Claude Code | 后台连接，按需在 ToolSearch/等待工具处等待；部分配置需要提前加载 | 可在后续模型请求发布新目录，需区别 alwaysLoad 和非交互模式 |
| Hermes | 后台发现、有界等待、迟到工具晚绑定；也支持 lazy/schema cache | 在 turn 边界刷新快照 |
| OpenClaw | session-scoped lazy runtime，在 discovery/use 处承担连接成本 | 配置或目录变化使缓存失效后重建 |
| Codex（原文后补样本） | 输入进入 pending queue，等待启动轮 settled 后释放 | 启动轮归属与逐 Server 状态隔离 |
| DeepSeek Harness | 原启动延迟文未覆盖 | 本次未补做调查，不推断实现 |

不要把“可以先输入”“首轮模型不等待”“同 turn 中动态加入工具”混作同一能力。OpenClaw 原资料未证明同 turn 先推理再等 MCP，也未给出统一重连次数；Claude Code 闭源核心的精确 UI 挂载顺序未核实。

## 原调查对 shikigen 的建议

**做什么**：composition root 启动后台 discovery，输入 loop 立即可用，提交后在总上限内等待，失败或超时有明确状态；invoke 前构建稳定工具快照。

**为什么**：先改善交互等待，避免慢 Server 污染同步 factory；失败也是 discovery 完成结果，不能永远 pending。

**API 方向**：异步 discovery task、ready tools + failed diagnostics、不可变 turn snapshot、turn boundary 重建 tool binding；reload 释放旧连接后再发现。ToolSearch、schema cache、首次调用连接是后续规模增大时的候选方案，本摘要不声明已实现。

## 原始来源

- [DeerFlow MCP 指南](https://github.com/bytedance/deer-flow/blob/main/backend/docs/MCP_SERVER.md#setup)、[扩展配置模型与路径](https://github.com/bytedance/deer-flow/blob/main/backend/packages/harness/deerflow/config/extensions_config.py)
- [Claude Code MCP 官方资料](https://code.claude.com/docs/en/mcp)
- [Hermes 启动发现源码](https://github.com/NousResearch/hermes-agent/blob/main/hermes_cli/mcp_startup.py)
- [OpenClaw MCP 客户端资料](https://github.com/openclaw/openclaw/blob/main/docs/cli/mcp.md#openclaw-as-an-mcp-client-registry)

原路径 `docs/research/deerflow-mcp-config.md`、`deerflow-mcp-null-handling.md`、`mcp-startup-latency-mainstream-agents.md` 在 `research-originals.zip` 中，保留完整配置示例、逐产品出处与原建议。
