# 稳定 ID 与消费者复用

14 号票实现记录。工具详情沿用[页面原型](../../../frontend/design.md#工具页面原型)，在概览卡核对、复制稳定 ID 和查看来源，在结构卡展开、复制完整 schema；没有输出结构时明确显示未声明。完整测试结果继续支持查看和复制 JSON／文本及所有执行事实。

## 复用入口

宿主向消费者提供 `ToolLibrary`，已有运行环境通过 `runtime.tools` 提供同一对象。消费者只保存工具 ID 和业务输入，不读取配置、源码或管理 MCP 会话，不需要创建 Agent、调用模型或建立 Run。单独使用工具库时，宿主可以直接创建 `ToolLibrary(config.source_path)`，退出时 `await tools.shutdown()`；不需要组装聊天存储。

| 接口 | 返回与失败方式 |
| --- | --- |
| `await tools.get_tool(tool_id)` | 最新已保存定义及读取版本。配置／缺失错误抛出 `ToolLibraryError`。定义包含源码路径，编辑源码使用已有详情接口。 |
| `await tools.build_tools(tool_ids)` | 按传入顺序去重后的 `list[BaseTool]`。一次协调读取检查整组选中定义的存在、启用和适配器支持，检查源码／连接，随后构建；任何一项失败整组报错，不返回部分集合。错误带对应 `resource_ids`，不交给 Registry 静默忽略。构建不执行业务、不连接远端。 |
| `await tools.execute_tool(tool_id, inputs)` | 完整 `ToolResult`。失败也返回明确的 `status`、`error` 和 `details.tool_id`；HTTP 入口为 `POST /api/tools/{id}/execute`，请求体 `{"inputs": {...}}`，结果位于 `data`。 |

缺失、禁用、适配器未登记、坏配置、源码缺失／接口变化和构建失败各自保留问题代码。重复调用名称或稳定 ID 会使保存／配置读取失败。工具库的装配不依赖按名称去重的 `ToolRegistry`，也不自动挂载当前聊天 Agent。

`BaseTool` 使用异步 `ainvoke(inputs)`。普通调用直接返回完整结果字典，包含 `status`、`data`、`data_available`、`error`、`duration_ms`、`details`。带 LangChain tool call ID 的调用返回 `ToolMessage`：正文 JSON 和 `artifact` 都保留完整结果；成功为消息 `success`，其余结果为消息 `error`，原始 timeout／cancelled 状态仍在结果中。MCP 内容块、structuredContent、原始附加字段以及 HTTP／Python 执行详情保留在相同封装内。执行结果仍通过已有凭据遮盖再交给消费者。

## 最新定义与本次内容

ID 是引用身份；调用名称和页面名称修改均不改变 ID。已构建工具的 `name`、`description`、`args_schema` 是装配时的展示信息，`metadata.tool_id` 标识稳定身份。调用方需要更新暴露给模型的名称／结构时，显式重新装配。

每次调用仅凭 ID 进入同一个已保存执行入口，重新读取最新定义、输入 schema、启用资格、适配器、关联连接和源码。旧对象可以接收新 schema 的输入，旧输入按新 schema 重新校验，不迁移、不强制转换，也不使用手动测试对禁用工具的例外。业务参数不会被 LangChain 的 `config`、`run_manager` 等注入参数覆盖。

取得定义／连接／完整源码后，遵循[13 号票的调用快照规则](config-conflicts-call-snapshot.md#本次调用内容)：当前调用继续使用所取得内容，随后改名、修改、禁用和删除只影响下一次调用。适配器登记与 `McpSessionProvider` 的执行 seam 保持原有边界，不增加插件安装或会话池。

## 非 LLM 字段传递

消费者负责先检查上游 `status`，再读取真实字段并明确组装下游具名 `inputs`。例如在注入 `tools` 和三项 ID 后：

```python
def successful_data(result):
  if result.status != "success":
    raise RuntimeError(result.error)
  return result.data


async def price_and_send(tools, http_id, python_id, mcp_id):
  order = successful_data(await tools.execute_tool(http_id, {}))
  priced = successful_data(await tools.execute_tool(python_id, {
    "order": order["order"],
    "quantities": order["quantities"],
    "active": order["active"],
    "note": order["note"],
  }))
  return successful_data(await tools.execute_tool(mcp_id, {
    "invoice": priced["invoice"],
    "quantities": priced["quantities"],
    "active": priced["active"],
    "note": priced["note"],
  }))
```

对象、数组、标量与 null 保留实际类型，不先序列化为字符串，不统一塞进 `args`。取不到上游字段就停止；下游缺少必填、类型或约束错误由同一执行入口拒绝，业务操作尚未发生。可选输出 schema 用于结构提示，不能代替下游实际输入校验；MCP 仍保留既有远端协议输出检查。

## 验证入口

- [公开 API 与复用接口](../../../tests/test_tool_consumers.py)：本地 HTTP → 真实 Python 子进程 → stdio MCP 三次直接执行；嵌套值／中文／null、错误停止、凭据遮盖、完整消息 artifact、同一 BaseTool 的最新 schema 和启用／删除资格，以及当前调用继续使用旧源码。
- [工具页面 DOM](../../../frontend/tests/tool-management-dom.test.mjs)：稳定 ID／来源、完整 schema 查看复制、未声明输出及既有完整结果与空值复制。
- [Windows 正式构建验收](../../../frontend/src-tauri/tests/tool_library_acceptance.py)：`test_stable_identity_schema_and_complete_result` 验证改名后 ID 不变、来源／schema／真实结果可见，并检查 1440px／390px 布局。

本票没有新增工作流编辑器、连线选择、定制 Agent 页面、引用关系表或当前聊天自动挂载。验证与审查结果见[验收记录](stable-id-consumer-reuse.review.md)。
