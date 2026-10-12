# 工具配置字段与适配器调查

调查日期：2026-10-12。研究票据：[调查主流 Agent 的工具录入项与发现机制](../wayfinder/tools-workflow/tickets/001-mainstream-tool-fields.md)。研究分支：`research/tool-configuration-fields-20261012`。

本文依据官方文档、规范和源码，研究 LangChain、Dify、AutoGen、Claude Code 与 MCP/OpenAPI。它们分别是框架、应用、客户端和协议，字段不应混成一个“所有主流 Agent 的标准”。下文的“建议”是待讨论的项目设计，不代表用户已经确认，也不表示项目已经支持。

## 结论与已确认范围

首版可以把工具分成两部分：**共有的调用定义**（名称、用途说明、输入 schema）和**各类型的执行配置**（MCP 服务引用、Python 代码、HTTP 请求）。管理用的稳定 ID、显示名、启用状态独立保存。适配器最终生成现有 `BaseTool`，继续交给 `ToolRegistry`；增加新类型时增加配置和适配器即可。这是结合当前仓库结构的建议，见[现状调查](../wayfinder/tools-workflow/baseline.md)。

用户已确认：先调查规划再开发；代码首版 Python；工具 CRUD 和手动测试；MCP 连接服务后发现并勾选工具，支持 stdio 与 Streamable HTTP；输入参数使用简单表格加高级 JSON Schema；输出先呈现真实 JSON/文本；HTTP 首版需要 OpenAPI 导入。完整工作流和定制 Agent 页面在后续实现。

最小录入面板建议如下，详细范围尚待相应决策票据确认：

| 创建方式 | 用户主要录入或选择 | 自动得到 |
| --- | --- | --- |
| MCP | 服务名称、连接方式、命令/URL、必要认证，连接后勾选工具 | 服务返回的工具名称、说明、输入 schema，及可能的输出 schema |
| Python | 工具名称、说明、输入参数、代码 | 稳定 ID、固定 Python 运行时与入口约定 |
| HTTP 手填 | 工具名称、说明、参数、method、URL、参数位置、必要认证 | 稳定 ID、真实响应 |
| OpenAPI 导入 | 文档、选中的接口、有效 server URL、凭据绑定 | 每个 operation 对应的 HTTP 工具草稿及参数映射 |

## 官方方案实际表达了什么

| 方案与证据边界 | 相关事实 | 对本项目的启发（建议） |
| --- | --- | --- |
| LangChain `BaseTool`；检查与本项目一致的 core 1.5.1 源码 | `name`、`description` 定义模型调用用途；`args_schema` 可为 Pydantic 类或 JSON Schema 字典。运行配置、回调和附加数据另有机制。[BaseTool 固定版本源码](https://raw.githubusercontent.com/langchain-ai/langchain/langchain-core%3D%3D1.5.1/libs/core/langchain_core/tools/base.py) | 复用现有调用接口；数据库配置不直接保存 `BaseTool` 实例。 |
| LangChain `StructuredTool`；现用参考页标注 core 1.6.4 | `from_function` 接收同步函数/协程；名称和说明可从函数名/docstring 推导，输入 schema 可显式传入或推导；`content_and_artifact` 表示正文和附加数据两个部分。[StructuredTool.from_function](https://reference.langchain.com/python/langchain-core/tools/structured/StructuredTool/from_function) | Python 和 HTTP 都可以包装成 `StructuredTool`，无需再造另一套运行工具基类。 |
| `langchain-mcp-adapters` 0.3.2，release commit `cc0f284` | adapter 将 MCP 定义转换为 `StructuredTool`，采用服务的 `inputSchema`；结构化结果放在 artifact。其代码不支持音频转换，会报错。[tools.py](https://github.com/langchain-ai/langchain-mcp-adapters/blob/cc0f284/langchain_mcp_adapters/tools.py) | MCP 元信息直接发现；测试面板须区分正文、结构化数据和转换失败。 |
| Dify Cloud 工具页，页面最后修改 2026-09-17 | Swagger API 工具由 OpenAPI 文档导入；MCP 通过 URL、名称、标识连接并导入工具，该页面限定 HTTP transport；工具可用于 Workflow/Agent。[Dify Tools](https://docs.dify.ai/en/cloud/use-dify/workspace/tools) | 可借鉴“连接/导入后选择工具”的流程；Dify 的 HTTP 限制不适用于本项目已确认的 stdio 支持。 |
| Dify Cloud Code 节点，最后修改 2026-07-02 | 配置输入变量、语言、代码与输出变量，Python 示例采用 `main` 返回字典；它运行在限制文件、网络和系统命令的沙箱内。[Code](https://docs.dify.ai/en/cloud/use-dify/nodes/code) | 借鉴固定入口，不复制其工作流输出变量系统；本机子进程不等于 Dify 沙箱。 |
| Dify Cloud HTTP Request 节点，最后修改 2026-08-27 | 配置 method、URL、headers、query、body、认证与连接/读/写超时；响应分别提供 body、status code、headers 等。[HTTP Request](https://docs.dify.ai/en/cloud/use-dify/nodes/http-request) | 作为 HTTP 执行字段参考；该节点并非可复用工具定义，仍需补充 name/description/schema。 |
| AutoGen 0.7.3 `FunctionTool` | 函数、description 为构造参数，name 可省略并从函数名得到；参数与返回值类型注解用于 schema。`strict` 是可选模式，不是所有工具的必填项。[FunctionTool](https://microsoft.github.io/autogen/0.7.3/reference/python/autogen_core.tools.html#autogen_core.tools.FunctionTool) | 可学习注解生成 schema，但页面 schema 与代码注解应有一个明确的权威来源。 |
| Claude Code 当前 MCP 文档；滚动文档，不声称对应单一安装版本 | 本地连接表达 command/args/env；远程表达 URL/headers，并提供 OAuth；连接配置与发现的工具分开。[Claude Code MCP](https://code.claude.com/docs/en/mcp) | 凭据属于服务连接；不让模型每次调用填写认证信息。 |

版本注意：项目 [uv.lock](../../uv.lock) 当前记录 `langchain 1.3.14`、`langchain-core 1.5.1`、`langchain-mcp-adapters 0.3.2`、`mcp 1.29.0`。官方 adapters 仓库已于 2026-09-17 归档，新的 `langchain.mcp` 要求 `langchain[mcp]>=1.4.0`，文档注明 beta；这不影响本轮以现有接口研究字段，不包含依赖迁移。[归档仓库](https://github.com/langchain-ai/langchain-mcp-adapters)、[现用 LangChain MCP 文档](https://docs.langchain.com/oss/python/langchain/mcp/tools)。

## 共有字段：模型调用定义与产品管理分开

以下是**首版建议**。“必填”指建议的项目校验，并非所有上游产品都规定必填。模型需要了解工具的用途和输入；项目同时需要长期保存、编辑和引用工具。

| 字段 | 来源与录入方式 | 首版建议 | 作用 |
| --- | --- | --- | --- |
| `id` | 系统生成 | 自动、不可随改名变化 | 后续工作流/Agent 的稳定引用，不发送为调用参数 |
| `kind` | 用户选择；导入时生成 | 必须为已注册类型，如 `mcp` / `python` / `http` | 选择适配器；不是模型输入 |
| `display_name` | 用户填写；发现/导入可预填 | 必填，可用中文 | 页面展示，不承担唯一身份 |
| `name` | 手工定义填写；发现/导入预填 | 必填，注册时校验唯一性，建议 ASCII snake_case | 模型发起调用时使用的名称 |
| `description` | 手填；MCP 从服务发现；OpenAPI 可预填 | 自建工具必填，说明“做什么、何时用” | 帮助模型选工具，区别于给开发者看的执行说明 |
| `input_schema` | 表格生成或高级编辑；MCP 自动发现 | 保存完整对象 schema；无参数也有对象 schema | 参数结构、类型、说明、必填性与约束 |
| `output_schema` | MCP/OpenAPI 可能提供；自建可选 | 可保存，首版不要求用户手写 | 描述结构化返回值，不是实际输出或输出映射 |
| `enabled` | 用户切换 | 系统给默认值 | 是否可供选择/执行；默认是否启用仍需决策 |
| `config` | 类型自己的表单或 importer 生成 | 每类独立校验 | 连接与执行配置；不发给模型作为输入 schema |
| `created_at` / `updated_at` | 系统生成 | 只展示 | 产品管理字段，不参与模型调用 |

`name`/`description`/输入 schema 的依据是 [LangChain 工具定义](https://docs.langchain.com/oss/python/langchain/tools)与上述 BaseTool/FunctionTool；稳定 ID、`kind`、启用状态、时间戳是本项目管理建议，不是 MCP 或 LangChain 的共同标准。中文显示名与调用名拆开，也是本项目建议。

简单参数表格已经确认四列：名称、类型、说明、必填。建议初期提供 `string`、`integer`、`number`、`boolean`，复杂 `object`、`array`、枚举和组合约束在高级 schema 中处理。完整 schema 应是权威存储，表格只是其可编辑视图；发现/导入的复杂 schema 不应被转成四列后重新保存而丢掉约束。这是为了兑现“简单表格 + 高级编辑”的实现建议，具体往返规则待决策。

**校验边界**：core 1.5.1 的 `_parse_input` 对字典形式 `args_schema` 直接返回输入，并不执行完整 JSON Schema 校验；Pydantic 路径才做其模型校验。因此“传了 args_schema 就完成本地参数校验”不成立。[固定版本源码，`_parse_input` 第 723–725 行](https://raw.githubusercontent.com/langchain-ai/langchain/langchain-core%3D%3D1.5.1/libs/core/langchain_core/tools/base.py)。建议工具服务在手动测试与运行的同一入口校验 schema 和实际参数，不只依赖前端表单。

## MCP：服务连接和发现工具分别配置

协议通过 `tools/list` 发现工具，`tools/call` 执行单个工具；工具列表可分页。工具 `name` 和 `inputSchema` 是必需定义，`title`、`description`、`outputSchema`、`annotations` 等可选。结果可以包含多个文本/图片/音频/资源块，以及独立的 `structuredContent`；工具执行错误可用 `isError` 表示。[MCP Tools，协议修订 2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)。

stdio 是客户端启动子进程并通过标准输入输出通信；Streamable HTTP 使用一个 MCP endpoint，由协议客户端处理 POST/GET 和可能的 SSE。后者不是“普通 HTTP 工具填写 method 后调用”。[MCP Transports，同一修订](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)。

### 服务录入项建议

| 字段 | 用户录入/自动 | 适用范围与建议 |
| --- | --- | --- |
| 服务稳定 ID | 自动 | 工具引用这个 ID；改服务显示名不应更换引用 |
| 服务名称 / 连接标识 | 用户 | 显示名可中文；注册前缀或连接标识建议稳定并校验重名 |
| `transport` | 用户选择 | 首版 stdio / Streamable HTTP；现项目配置键分别为 `stdio` / `http` |
| `command` | 用户，stdio 必填 | 可执行文件；与参数分开保存，不拼成一个 shell 命令 |
| `args` | 用户，stdio 可留空 | 保存数组，空时传 `[]`；SDK 类型要求这个键存在 |
| `env` | 用户，stdio 按需 | 服务进程的环境变量；凭据可用受控引用，不是工具调用参数 |
| `cwd` | 用户，stdio 可选 | 工作目录；不用来定义每个工具的输入 |
| `url` | 用户，HTTP 必填 | MCP endpoint，例如 `https://example.com/mcp` |
| `headers` | 用户，HTTP 按需 | 认证或服务要求的附加头 |
| 连接/请求与流读取超时 | 默认，高级可改 | 与“工具总执行超时”分别说明，不能当成同一个值 |
| 连接状态 / 最近发现时间 | 系统 | 诊断信息，不是用户录入的定义 |

SDK 字段与必需键依据 [adapters 0.3.2 sessions.py](https://github.com/langchain-ai/langchain-mcp-adapters/blob/cc0f284/langchain_mcp_adapters/sessions.py)。当前项目的 [app_config.py](../../packages/harness/shikigen/app_config.py)已经包含上述两种连接的大部分字段；ID、显示名、状态和页面分组是新增产品建议。编码、session kwargs、自动重连策略等不用首版都暴露成表单。

### 发现出的单个工具

| 内容 | 上游要求/来源 | 页面建议 |
| --- | --- | --- |
| 远程工具名 + 服务关联 | name 必需；服务关联由项目补充 | 用 `(server_id, remote_name)` 找到同一远程工具；本地另有稳定 tool ID |
| 名称、用途、输入 schema | 自动发现；description 在协议中可选 | 默认只读展示服务定义，不要求重复录入 |
| 输出 schema、title、annotations、其他元信息 | 服务可能提供 | 原样保存可用部分；不作为全部必填字段 |
| 启用选项 | 用户勾选 | 保存选择，不把未勾选工具注册给使用方 |
| 名称前缀 / 本地调用名 | 项目生成 | 避免两个服务工具同名；当前 loader 已开启服务名前缀 |

上游定义见上述 [MCP Tools](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)；生成与选择规则是建议。现有 [mcp_loader.py](../../packages/harness/shikigen/tools/mcp_loader.py)可按服务发现工具，并隔离发现失败。建议完整取完分页再展示；重新发现时按稳定服务关联匹配，保留已有选择。工具被远端移除或 schema 变化，应在页面提示，具体生效策略待决策。

建议测试面板保留真实结果的类型、结构化数据和错误状态；初期无需完整呈现所有多媒体，但不能把不支持的结果伪装成成功文本。尤其当前 adapter 的音频转换限制与 MCP 协议允许音频是两回事，见上面的固定版本 `tools.py`。

## Python：定义字段与运行时约定

这些是适合本项目的建议，并不是统一的 Python 工具协议。固定 `main` 的灵感来自 Dify Code；AutoGen/LangChain 更常用函数签名和注解构造工具定义，均见前面的官方证据。

| 字段或约定 | 谁提供 | 首版建议 |
| --- | --- | --- |
| 共有 name、description、input schema | 用户 | 使用共有参数编辑器，不增加第二张输入变量表 |
| `language` | 固定/自动 | 首版 `python`，页面无需让用户选择不可用语言 |
| `code` | 用户必填 | 多行代码编辑器；保存时做语法与入口检查，不因保存执行用户代码 |
| `entrypoint` | 固定/自动 | 统一 `main`，初期不增加任意入口选择器 |
| 输入方式 | 项目约定 | 验证后的参数对象展开为 `main(**arguments)`；参数名与 schema 对应 |
| 返回方式 | 项目约定 | 返回 JSON 可序列化值或文本；推荐示例返回 dict；print 为调试日志，不当正式返回值 |
| `timeout_seconds` | 默认，可高级调整 | 统一执行入口必须能够中止超时进程；默认值在执行票据定稿 |
| 环境、工作目录、依赖 | 默认，必要时高级配置 | 复用明确的项目 Python 环境；初期不提供页面自动 pip 安装 |
| output schema | 可选 | 首版不要求输出变量声明或复杂映射，测试展示实际结果 |

建议采用显式输入 schema 为权威来源，代码注解仅辅助学习；如果选择从签名生成 schema，则需要单独决定编辑表格后的同步规则。不要一边让表格可改、一边在执行时重新推导并覆盖它。

示例仅说明约定：

```python
def main(a: int, b: int) -> dict:
    return {"sum": a + b}
```

对应输入 schema 为含必填整数 `a`、`b` 的对象；测试参数 `{"a": 2, "b": 3}` 的正式结果为 `{"sum": 5}`。这段代码不会在本轮运行。对于学习项目，本机子进程加超时是一种可讨论的运行方式；它拥有宿主进程可授予的文件/网络能力，不能称为安全沙箱。生产级沙箱在当前地图范围外，具体工作目录、环境变量和取消行为仍需确认。

## HTTP：一个工具执行一个请求

首版建议保留手填入口，并增加已确认需要的 OpenAPI 导入；二者最终生成相同的 HTTP 定义，使用同一个运行适配器。手填是否也保留为用户可见入口、导入兼容范围仍需后续定稿。

| 字段 | 来源/是否必须 | 首版建议 |
| --- | --- | --- |
| 共有字段 | 手填或导入生成 | 与 Python 共用工具定义和参数编辑器 |
| `method` | 必须，导入可生成 | GET/POST/PUT/PATCH/DELETE/HEAD/OPTIONS；遇到未支持方法明确报导入诊断 |
| `url` / base URL + path | 必须，导入预填后用户确认 | HTTP/HTTPS；路径模板明确替换路径参数 |
| 参数映射 | 有动态参数时必须 | 除名称/类型/说明/必填，再明确 path/query/header/body 的位置；不凭参数名猜测 |
| 固定 headers / query | 可选，用户或导入 | 固定值与模型调用参数分开 |
| body 类型与结构 | 需要请求体时配置；导入生成 | 初期建议 JSON；原始文本可另评估，不默认支持上传/下载 |
| 认证模式与凭据引用 | 按接口要求 | 建议 none、Bearer、API key；API key 的 header 名或 query 名须明确 |
| 请求超时 | 默认，可调 | 可先对外一个清楚的请求超时，内部不必照搬 Dify 所有旋钮 |
| 响应处理 | 系统默认 | JSON 可解析时展示 JSON，其他展示文本；保留 status、必要 headers 与 body |
| 输出 schema | 可选，导入可能提供 | 保留来源，不要求把实际响应重新映射成固定几个输出变量 |

method/URL/headers/query/body/认证和响应元信息的产品参考是 [Dify HTTP Request](https://docs.dify.ai/en/cloud/use-dify/nodes/http-request)；OpenAPI 的参数位置与请求体是另一层接口定义，见下面规范。表中的首版子集、超时 UI、稳定 ID 和适配器复用均为项目建议。

凭据不应出现在传给模型的 input schema、工具说明、测试日志或导出示例中。建议绑定环境变量或专门的密钥引用；现项目仅支持整个字符串 `$ENV_NAME` 解析，不能直接假定 `Bearer $ENV_NAME` 会展开。[app_config.py](../../packages/harness/shikigen/app_config.py)。具体凭据保存方式留给执行配置票据，不为首版建设完整凭据平台。

## OpenAPI：导入范围必须单独明确

规范的接口定义包含 `paths` 下的 operations；`operationId` 可选，参数位置为 path/query/header/cookie；请求体单独放在 `requestBody.content`。servers 可以被 path/operation 覆盖；security 的数组表示备选方案、同一对象内的方案需同时满足。JSON/YAML 都可表达文档，引用可指向文档内部或外部。[OAS 3.1.1 的固定版本规范](https://spec.openapis.org/oas/v3.1.1.html)。这些是格式事实，不是本项目已支持的功能清单。

3.0 的 schema 是较早 JSON Schema 的扩展子集，`nullable` 与 3.1 的 JSON Schema 2020-12/null 类型表达不同，不能只改版本字符串。[OAS 3.0.4 Schema Object](https://spec.openapis.org/oas/v3.0.4.html#schema-object)、[OAS 3.1.1 Schema Object](https://spec.openapis.org/oas/v3.1.1.html#schema-object)。这里固定比较 3.0/3.1，不宣称它们是最新规范。

Dify 当前源码 `auto_parse_to_tool_bundle` 尝试 JSON 和 YAML；parser 枚举 HTTP methods，取首个顶层 server，能处理部分文档内 `$ref`，缺 operationId 时生成名称。当前检查文件没有证明完整 3.0/3.1 schema 验证或任意外部引用支持；因此不能借用它宣称完整兼容。[Dify parser.py，main 于调查日读取](https://github.com/langgenius/dify/blob/main/api/core/tools/utils/parser.py)。Cloud 页明确提供粘贴和 URL 导入，但没有逐项承诺上述版本和复杂特性。[Dify Tools](https://docs.dify.ai/en/cloud/use-dify/workspace/tools)。

以下是为了保持学习规模的**建议支持清单，待用户确认**：

| 决策点 | 建议首版范围 | 为什么要单独限定 |
| --- | --- | --- |
| 导入输入 | 粘贴或上传单份 JSON/YAML；URL 导入作为可选补充 | 文档 URL 获取与请求执行是不同能力；先实现确定的单文档流程 |
| 版本 | 识别 3.0.x、3.1.x，支持公布的常用子集；其他版本明确提示 | 支持常用字段不等于完整规范实现；3.0 schema 要转换后再用于工具输入 |
| 操作选择 | 解析后列出 method、path、名称、说明；勾选后生成草稿 | 一个文档通常有多个接口，一个可调用工具仍只执行一个 operation |
| 名称 | 优先 operationId，缺失时从 method/path 生成；检查冲突 | 名称不能代替持久 ID；导入前应展示最终调用名 |
| URL | 按 operation > path > 根级的 server 配置解析，再允许用户选择/覆写；相对地址须补全 | 不能在所有文档中固定取第一个根级 URL；server variables 先用可确认的值 |
| 普通参数 | 合并 path 级与 operation 级参数，按 `(name, in)` 覆盖；支持基础 path/query/header 类型 | 参数名可能重复，不能直接扁平覆盖；路径参数必填规则需保留 |
| 参数序列化 | 首版支持标量、常见基础 query 数组；展示采用的 style/explode | 深层对象、特殊序列化先提示未支持，避免发送形状不同的请求 |
| JSON 请求体 | 保留对象/数组/嵌套 schema 与必填性；选择一个受支持 content type | 不把 body properties 展平成普通 query；multipart/binary 暂不默认支持 |
| 引用 | 支持所选接口用到的文档内 `#/...`，包括 schema/parameter/requestBody；检测循环 | 不为展开而无限递归；外部文件/URL 引用先给具体未支持提示 |
| 输入归一化 | 保留参数位置；建议 path/query/header/body 分组或保存显式映射 | 与共有四列表格之间的展示方式待确认，不能为了表格抹掉 HTTP 位置 |
| schema 约束 | 常见类型、required、enum、基础数组/对象；完整保存原始片段 | 对 oneOf/allOf、递归、特殊 dialect 等，按明确支持能力诊断，不能静默删掉约束 |
| 认证 | 识别 securitySchemes 和 operation/root security；先支持可绑定的 Bearer 与 API key（header/query） | 文档描述认证方式，不携带真实密钥；选择一套备选要求并绑定所有必需凭据 |
| 不支持的认证 | OAuth/OIDC、cookie auth、mTLS 等先提示并阻止不完整定义投入执行 | 不把“手填一个 token”说成完成了 OAuth 流程，也不自动改成匿名 |
| 输出 | 保存响应 schema 作为参考，测试呈现实际 body/status | 多状态码、多个 media type 不适合强行合成一个未经讨论的输出 schema |
| 再导入 | 首版先导入为独立草稿；再次导入检测重名，避免默认覆盖既有 ID | 自动同步、版本迁移和已被工作流引用后的更新可后续决定 |

上表是建议的实现取舍，不表示四列编辑器已经能覆盖所有 schema。导入预览最好给每个接口“可创建 / 需要补配置 / 未支持及原因”，用户只确认自己选择的接口。严格拒绝部分类型可能影响实际接口文档可用性；应在 [确定 OpenAPI 导入的首版范围](../wayfinder/tools-workflow/tickets/005-openapi-import-scope.md)用用户常用文档样例确认。

## 适配器接缝与可复用引用

建议采用这一条路径：

```text
用户录入 Python / HTTP 配置 ─────────────┐
OpenAPI 文档 → importer → HTTP 草稿 ────┼→ 类型适配器 → BaseTool → ToolRegistry
MCP 服务连接 → 发现 → 选择的工具定义 ───┘
```

importer 只在导入/更新定义时运行；HTTP adapter 在每次调用时构造请求。MCP adapter 负责根据连接调用远程工具；Python adapter 负责约定入口、参数和执行进程。管理页和后续工作流/Agent 使用稳定 tool ID；调用时由服务解析定义、选择 adapter、生成当前运行所需的 BaseTool 集合。这是项目设计建议；依据现有 [Registry](../../packages/harness/shikigen/tools/tool_registry.py)与 [MCP loader](../../packages/harness/shikigen/tools/mcp_loader.py)，不需要另造通用插件平台。

首版可从一个 `kind -> adapter` 映射和很小的构建接口开始；不必提前设计多级工厂、继承树或让各 adapter 自己持久化配置。工具管理服务负责保存、引用与输入校验，adapter 负责各类型转换和执行细节。MCP 服务发现一组工具是来源层行为，而对外每个 BaseTool 仍是一项可调用工具。

Registry 当前以 `name` 去重并忽略后注册的同名工具。建议保存/导入时就显示名称冲突，而不是等注册后静默少一个工具。具体全局调用名规则、引用后删除行为和运行中编辑如何生效，仍需设计决策。

## 尚待用户参与的决策与研究限制

1. MCP 服务与工具的持久关系、调用名、启用默认值、重新发现/更新时保留哪些内容。
2. 简单表格和高级 schema 的往返规则，以及导入复杂 schema 的可编辑范围。
3. 上述 OpenAPI 子集、导入方式和认证边界，最好用实际常用接口文档确认。
4. Python 进程环境/工作目录、超时与取消；HTTP/MCP 的认证保存、失败类型和测试结果契约。
5. CRUD、生效与删除被引用工具的行为；未来工作流/Agent 的引用和解析接口。

本轮只进行文档与源码阅读，没有安装依赖、连接 MCP 服务、运行用户代码、发送测试 HTTP 请求或验证应用实现。Dify Cloud 滚动页面不等于每个自部署版本；Dify main 源码不是完整兼容测试证据；Claude Code 滚动页面不代表用户机器安装版本；LangChain 最新 API 不自动适用于当前 lockfile。没有用二手文章或机器人 issue 评论作为事实依据，没有纳入 OpenAI SDK 或 DeerFlow 的兼容结论。
