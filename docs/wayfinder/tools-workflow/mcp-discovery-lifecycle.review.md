# Ticket 09 实现审查

2026-10-20，固定基点 `e2c125244c029154fbbf68e61b2edd29deecf819`。本票开始时工作区干净；两名独立审查代理分别检查基点至工作区的实现差异。规格为 `.scratch/tools-workflow/issues/09-mcp-discovery-lifecycle.md`，实现记录见[连接生命周期](mcp-discovery-lifecycle.md)。

用户此前明确决定保留认证、移除通用 credential，MCP headers 直接编辑保存回填，隐藏机制等待统一设计；不将其计为本票遗漏。完整磁盘并发强化留给 13。

## Standards

硬性违反：0；判断性建议：0。

职责符合 README 的模块边界：发现差异、来源更新与级联删除留在 runtime；HTTP 删除入口仅校验、委托和映射错误，符合项目约定。页面延续 RJSF，预览事实、所属工具和删除清单来自后端，操作位于既有详情栏和确认弹层，符合前端设计。固定代码异味基线未发现值得报告的实际维护性问题。

## Spec

遗漏／部分实现：0；范围扩张：0；实现错误：0。

已直接核对发现前同次读取快照、应用版本验证、来源匹配、全部验证后单次提交、ID 和本地字段保留、普通保存与草稿来源权限、失败／未发现保留、级联删除及 UI 异步恢复。保存后的详情回读以 sequence 核对，避免跨后端会话的迟到离开操作。

全量后端发现生命周期测试仍使用上次模块拆分前的 `composition.load_mcp_tools`。已将 MCP 阶段的 mock 改到实际查找位置 `core.tool_assembly.load_mcp_tools`；两路复核确认进入／取消信号、停止等待、清理与逐阶段重新打开存储的断言均未改变，0 项新增发现。该文件 3 项回归通过。

最终验证：后端全量 431 项（430 通过、1 跳过）；前端全量 378 项通过；生命周期专项 3 项、MCP 页面专项 8 项及真实 Windows WebView 1 项通过。Ruff、格式检查、后端源码 ty、TypeScript／Vite 构建通过，截图已查看。首次全量的旧 mock 路径和 Vite 偶发超时均已有修正／复测及最终全量证据，详见[实现记录](mcp-discovery-lifecycle.md)。

结论：Standards 0 项遗留；Spec 0 项遗留。
