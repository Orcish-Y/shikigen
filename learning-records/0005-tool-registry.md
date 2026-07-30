# 工具注册中心：多来源工具收集与去重

用户实现了 `ToolRegistry`——工具的中央注册表。关键设计决策：

- 同名冲突：`logger.warning` + 跳过，不抛异常。对应 deer-flow 的 `get_available_tools()` 行为——多来源（本地、MCP、社区）收集工具时重名是正常的。
- 实例属性 `self.tools` 而非类属性——修正了初版中多个 registry 实例共享同一个 dict 的 bug。
- `create_default_registry()` 是 deer-flow `get_available_tools()` 的等价物——单一入口，预填所有本地工具。

**Evidence**: `tools/__init__.py`，`main.py` line 19 正确使用 `.list()`。

**Implications**: 工具系统的基础设施就绪。下一步可以自然地引入 Middleware——middleware 通过 `ToolRuntime` 访问工具，而注册表是工具的唯一来源。
