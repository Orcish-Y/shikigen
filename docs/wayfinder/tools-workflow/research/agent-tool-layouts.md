# 主流 Agent 框架如何组织工具

调研日期：2026-10-20。范围只看 OpenAI Agents SDK、LangChain/LangGraph 与 Pydantic AI 的官方文档和源码。

## 结论

主流框架通常把**单个工具的模型可见契约**（名称、说明、参数 schema）和它对应的业务处理函数放在同一个工具对象或函数附近；它们更明确地把**工具注册/Agent 组装**与**运行时调度、校验、并发、错误处理**分开。也就是说，常见的分层不是“所有 schema 一个目录、所有业务函数另一个目录”，而是“具体工具定义与业务动作相邻，工具清单和通用执行管线独立”。Pydantic AI 也遵循这一点：`Tool` 持有函数及其 schema，而 `ToolManager`、toolsets 与执行/Agent graph 分散在不同模块。

## OpenAI Agents SDK

- 文档说明 `@function_tool` 可以从 Python 函数自动生成工具名、描述和输入 schema；手写 `FunctionTool` 时则在同一个对象上提供 `name`、`description`、`params_json_schema` 与 `on_invoke_tool`。因此 SDK 的单个工具契约和 handler 可以共置。[Tools 文档](https://openai.github.io/openai-agents-python/tools/)
- 官方基础示例把 `get_weather` 函数及其参数类型放在 `examples/basic/tools.py`，然后将函数放入 `Agent(tools=[get_weather])`。这展示了小型应用可将工具与 Agent 组装放一起的最简用法。[官方 tools.py 示例](https://github.com/openai/openai-agents-python/blob/main/examples/basic/tools.py)
- SDK 本身把运行时执行单独放在 `src/agents/run_internal/tool_execution.py`；源码说明该模块负责 run pipeline 中的执行期逻辑、approval 与 payload coercion。仓库维护指南也要求把运行逻辑放在 `run_internal/`，让 `run.py` 保持编排入口职责。[tool_execution.py](https://github.com/openai/openai-agents-python/blob/main/src/agents/run_internal/tool_execution.py) · [维护指南](https://github.com/openai/openai-agents-python/blob/main/AGENTS.md)

**可借鉴点：** 工具清单或 Agent 配置可以单独组装，框架级执行流水线也应独立；具体工具的 schema 与领域 handler 通常仍属于同一个工具定义边界。

## LangChain / LangGraph

- LangChain 的官方工具文档把工具描述为带输入/输出约定的可调用函数；基本例子用 `@tool` 装饰业务函数，从类型提示和 docstring 得到 schema 与说明。创建 Agent 时再把工具列表传给 `create_agent`。[LangChain Tools 文档](https://docs.langchain.com/oss/python/langchain/tools)
- LangChain Core 源码将工具抽象与函数适配器分在 `langchain_core/tools/` 下，例如 `base.py`、`convert.py`、`structured.py`；`@tool` 的职责是把函数或 Runnable 转成 `BaseTool`，并从签名推导 schema。[BaseTool](https://github.com/langchain-ai/langchain/blob/master/libs/core/langchain_core/tools/base.py) · [函数/Runnable 转换器](https://github.com/langchain-ai/langchain/blob/master/libs/core/langchain_core/tools/convert.py)
- LangGraph 另有运行时执行节点 `langgraph/prebuilt/tool_node.py`。官方文档称 `ToolNode` 负责工具执行，并处理并行调用、错误和 state 注入；官方工作流示例也是先定义 `@tool` 函数，再把函数集合传给 `ToolNode([...])`。[ToolNode 源码](https://github.com/langchain-ai/langgraph/blob/main/libs/prebuilt/langgraph/prebuilt/tool_node.py) · [LangGraph agent/workflow 文档](https://github.com/langchain-ai/docs/blob/main/src/oss/langgraph/workflows-agents.mdx)

**可借鉴点：** 领域工具函数由应用定义；Agent/图的工具清单在组装处集中；调用分发和结果转成工具消息由 `ToolNode` 负责。框架把执行机制拆开了，但示例中的具体工具仍把契约和函数放在一起。

## Pydantic AI

- 官方工具文档支持用 `@agent.tool` / `@agent.tool_plain` 注册函数，也可以显式创建可复用的 `Tool`；框架从 Python 类型提示和 docstring 构造供模型使用的 schema。[Tools 文档](https://ai.pydantic.dev/tools/)
- 源码中的 `Tool` 同时持有函数、名字、描述和 `FunctionSchema`，生成 `ToolDefinition` 供模型请求使用。因此它也没有默认要求把每个工具的参数定义与 handler 拆成独立文件。[tools.py](https://github.com/pydantic/pydantic-ai/blob/main/pydantic_ai_slim/pydantic_ai/tools.py)
- 执行组织由独立模块承担：仓库架构指南将 Agent loop 放在 `_agent_graph.py`，工具发现、校验、执行、审批和封装归给 `tool_manager.py`、`tools.py` 与 `toolsets/`。[架构指南](https://github.com/pydantic/pydantic-ai/blob/main/agent_docs/pydantic-ai-slim.md) · [Agent graph](https://github.com/pydantic/pydantic-ai/blob/main/pydantic_ai_slim/pydantic_ai/_agent_graph.py)

**可借鉴点：** 复用 tool object 或 toolset 来组织相关工具；把集中发现、筛选与执行放到管理层，但让单个工具的契约继续跟随其函数定义。

## 对当前目录拆分的启示

当前项目里，这两类职责已经能从调用方区分出来：`core/agent.py` 用 `ToolRegistry`、内置 `BaseTool` 和 `mcp_loader` 组装传给 LangChain Agent 的工具；`runtime/tool_library.py` 管理持久工具定义，并通过 `ToolExecutor` 和 HTTP/Python/MCP adapters 执行工具库中的定义。`contracts/tool_definitions.py` 与 `contracts/tool_execution.py` 分别承载定义和执行协议。

如果要整理目录，建议按调用边界把两组代码分开，而让一个内置工具的 LangChain schema/描述和 handler 继续共置：

```text
shikigen/
  agent_tools/
    builtin/           # add、filesystem、web、time 等模型可调用工具
    registry.py        # Agent 使用哪些工具
    task_tool.py       # 子 Agent 工具
    mcp_loader.py      # 将外部 MCP 工具接入 LangChain Agent
  tool_execution/
    executor.py        # 工具库调用的校验、预算和分发
    adapters/          # HTTP、Python、MCP 的执行实现
    mcp/               # MCP session 和 transport 辅助
  contracts/           # 可持久化定义与执行协议
  runtime/tool_library.py  # 工具库配置、CRUD、测试等应用服务
```

这里的文件名是职责示意，不是必须照搬的框架约定。若把“工具定义”与“业务实现”拆成两个平行列表，需要额外维护名称/schema 到 handler 的映射；因此优先拆 Agent 工具包与工具库执行包，再按工具或领域分文件。`runtime/tool_library.py` 继续作为应用服务，通过依赖组装使用执行器。
