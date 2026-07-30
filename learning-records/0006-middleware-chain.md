# Middleware 链：AgentMiddleware 的 4 个生命周期 hook

用户实现了两个 middleware，并在实践中纠正了一个关键误解：`wrap_model_call` vs `wrap_tool_call`。

**核心理解**：
- `wrap_model_call(ModelRequest)` — 包装整个 LLM 调用。`ModelRequest` 没有 `tool_call` 属性。
- `awrap_tool_call(ToolCallRequest)` — 包装单个工具执行。`request.tool_call` 有 `name`、`id`、`args`。
- 工具错误处理必须用 `awrap_tool_call`，不能用 `wrap_model_call`。

**GraphBubbleUp 透传**：LangGraph 内部异常，用于中断 graph，不能吞掉。deer-flow 同样处理。

**顺序规则确认**：`ToolErrorHandlingMiddleware` 排在第一位 → 最外层 → 逆序执行时 `awrap_tool_call` 最后跑 → 能捕获内层所有异常。

**Evidence**: `middleware/tool_error_handling_middleware.py`, `middleware/logging_middleware.py`, `main.py` line 22。
