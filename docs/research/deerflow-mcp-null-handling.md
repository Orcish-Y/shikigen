# DeerFlow MCP 空值处理

> 调研基线：ByteDance 官方 `bytedance/deer-flow` 仓库 `main` 分支，核对日期 2026-08-12。只使用官方源码和官方文档。

## 结论

DeerFlow 当前的文件配置不是 `{"mcp": {"servers": ...}}`，而是 `extensions_config.json` 顶层的 `mcpServers`。Python 模型内部字段名为 `mcp_servers`，通过 alias 接受公开 JSON 名称。[官方示例](https://github.com/bytedance/deer-flow/blob/main/extensions_config.example.json)；[配置模型](https://github.com/bytedance/deer-flow/blob/main/backend/packages/harness/deerflow/config/extensions_config.py#L140-L155)

核心定义为：

```python
mcp_servers: dict[str, McpServerConfig] = Field(
    default_factory=dict,
    description="Map of MCP server name to configuration",
    alias="mcpServers",
)
```

因此三种输入的处理是：

| `extensions_config.json` 输入 | 结果 |
| --- | --- |
| `{}`，即缺少 `mcpServers` | 使用 `default_factory=dict`，得到 `config.mcp_servers == {}` |
| `{"mcpServers": {}}` | 合法，得到 `config.mcp_servers == {}` |
| `{"mcpServers": null}` | 不合法；字段类型是 `dict[...]` 而不是 `dict[...] | None`，Pydantic 产生 `ValidationError` |

DeerFlow 没有把 `null` 转为空字典的 field/model validator。加载函数把 JSON 交给 `ExtensionsConfig.model_validate(config_data)`；该校验异常随后被通用异常分支包装成 `RuntimeError("Failed to load extensions config ...")`。[文件加载源码](https://github.com/bytedance/deer-flow/blob/main/backend/packages/harness/deerflow/config/extensions_config.py#L229-L252)

换言之，DeerFlow 的语义是：**MCP Server 集合可以不配置或配置为空，但不能显式写成 `null`。** 官方文档给出的配置形状也始终把 `mcpServers` 表达为“Server 名称到配置的映射”。[官方 Backend README](https://github.com/bytedance/deer-flow/blob/main/backend/README.md#extensions-configuration-extensions_configjson)

## 配置文件本身不存在

这与字段缺失是另一个层级。如果使用自动搜索且完全找不到 `extensions_config.json`，`resolve_config_path()` 返回 `None`，`from_file()` 会直接构造空配置：

```python
return cls(mcp_servers={}, skills={})
```

所以此时 MCP Server 同样是空字典。显式参数或 `DEER_FLOW_EXTENSIONS_CONFIG_PATH` 指向不存在的文件则会抛 `FileNotFoundError`，不会静默使用空配置。[路径解析与空配置源码](https://github.com/bytedance/deer-flow/blob/main/backend/packages/harness/deerflow/config/extensions_config.py#L161-L243)

## Gateway API 的区别

DeerFlow 的 `PUT /api/mcp/config` 使用另一个请求模型：

```python
class McpConfigUpdateRequest(BaseModel):
    mcp_servers: dict[str, McpServerConfigResponse] = Field(...)
```

这里 `Field(...)` 表示请求字段必填，因此 API 更新请求的行为更严格：

| 请求体 | 结果 |
| --- | --- |
| `{}` | 字段缺失，FastAPI/Pydantic 请求校验失败（422） |
| `{"mcp_servers": null}` | 类型不符，请求校验失败（422） |
| `{"mcp_servers": {}}` | 合法，表示把 MCP Server 集合更新为空 |

依据：[Gateway 请求模型](https://github.com/bytedance/deer-flow/blob/main/backend/app/gateway/routers/mcp.py#L376-L390)；[官方 API 文档](https://github.com/bytedance/deer-flow/blob/main/backend/docs/API.md#mcp-configuration)

## 对当前项目的直接启示

若要复刻 DeerFlow 的配置语义，应写成非 nullable 的字典并提供空字典默认值：

```python
from typing import Any

from pydantic import BaseModel, Field


class McpConfig(BaseModel):
  servers: dict[str, dict[str, Any]] = Field(default_factory=dict)
```

这样字段缺失和 `{}` 都会得到空字典，而显式 `null` 会尽早报配置错误。只有业务上确实需要区分“未设置/禁用”与“已设置为空”时，才应改为 `dict[...] | None = None`；这不是 DeerFlow 当前采用的做法。
