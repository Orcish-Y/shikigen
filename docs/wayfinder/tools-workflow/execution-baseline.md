# 工具执行接缝调查

调查日期：2026-10-12。只读调查，未修改应用代码、运行产品测试或读取实际凭据。

本 worktree 没有 `.venv`。锁定依赖的实现从主工作区 `C:/code/shikigen-agent/.venv/Lib/site-packages` 只读检查，版本与本 worktree 的 [uv.lock](../../../uv.lock) 一致：langchain-core 1.5.1、langchain-mcp-adapters 0.3.2、MCP SDK 1.29.0、HTTPX 0.28.1、jsonschema 4.26.0。此处记录现状事实，不替用户决定产品契约。

## Python 与取消

- 项目要求 Python >=3.12；桌面开发态以项目虚拟环境解释器启动后端。没有独立代码工具环境或自动安装工具依赖机制。新子进程可以复用后端解释器；代码、参数和返回值协议需要新增。见 [backend.rs](../../../frontend/src-tauri/src/backend.rs)、[harness 依赖](../../../packages/harness/pyproject.toml)。
- 现有 shell 工具采用同步 `subprocess.run(shell=True)`，30 秒超时，合并 stdout/stderr 并截取 4000 字符，不能直接承担结构化 Python 入口协议。见 [filesystem.py](../../../packages/harness/shikigen/tools/builtin/filesystem.py)。
- 当前 Run 取消信号没有代码工具子进程句柄；桌面 Job Object 针对整个后端进程树，不是每项工具的终止接口。取消 Run 不能证明单项工具及其派生进程都停止。见 [execution.py](../../../packages/harness/shikigen/core/execution.py)、[run_execution.py](../../../packages/harness/shikigen/runtime/run_execution.py)、[windows.rs](../../../frontend/src-tauri/src/process/windows.rs)。
- `asyncio.timeout()` 可限制异步执行预算，但取消与清理仍可能继续耗时；不代表远端操作已撤销。见 [Python 官方文档](https://docs.python.org/3.12/library/asyncio-task.html#timeouts)。
- 普通函数可以通过 `function(**inputs)` 按字典键传关键字参数；默认参数在未提供时按函数定义生效。仅位置参数不能用关键字传入，可变位置参数需要位置值规则。inspect.Signature.bind 可以检查参数是否匹配签名；这些是 Python 调用事实，不代表本项目已实现全部签名支持。见 [Python 参数文档](https://docs.python.org/3.12/tutorial/controlflow.html#special-parameters)、[inspect 签名绑定](https://docs.python.org/3.12/library/inspect.html#inspect.Signature.bind)。
- Python AST 的 FunctionDef/arguments/arg 提供函数名、参数种类、默认表达式和注解，可静态提取签名骨架，不需导入或执行源码。是否有默认表达式可决定参数可省略性；缺少注解时无法仅据名称/默认值可靠知道所有允许类型，自定义类型、动态签名和 **kwargs 业务字段也需要额外信息。见 [AST 官方参数节点](https://docs.python.org/3.12/library/ast.html#ast.arguments)。
- 仓库已有 [add.py](../../../packages/harness/shikigen/tools/builtin/add.py) 的 LangChain @tool 自动 schema，但它接受真实函数对象；锁定实现使用 inspect.signature/Pydantic，并通过 get_type_hints 处理注解，需要运行命名空间，不是源码草稿的静态解析器。当前没有源码 AST 参数提取服务。
- Python 类型注解本身不自动强制检查运行参数；本项目仍需按生成或补充后的 JSON Schema 实施输入校验。见 [Python typing 官方说明](https://docs.python.org/3.12/library/typing.html)。

## HTTP

- HTTPX 已是直接依赖，已有异步调用；尚无通用 HTTP 定义或结果契约。见 [web_fetch.py](../../../packages/harness/shikigen/tools/builtin/web_fetch.py)、[web_search_client.py](../../../packages/harness/shikigen/tools/builtin/web_search_client.py)。
- HTTPX 超时区分连接、读取、写入和连接池等待；不是整个调用总时长。通用 AsyncClient 默认不跟随重定向，默认读取环境代理/证书配置。见锁定 SDK `_config.py`、`_client.py` 与 [HTTPX 官方超时文档](https://www.python-httpx.org/advanced/timeouts/)。
- 锁定 HTTPX 将 query 的 `None` 编为空字符串；`json=None` 表示不发送 JSON body。需要区分缺失、空字符串与 JSON `null`，不能直接把 SDK 默认当作产品规则。见锁定 SDK `_utils.py`、`_content.py`。
- 项目已有严格 JSON 值边界，禁止 NaN/Infinity，可用于工具参数及结果。见 [messages.py](../../../packages/harness/shikigen/contracts/messages.py)。

## MCP

- 现有 loader 的发现路径新建会话、初始化、获取工具列表后关闭；生成工具每次调用另建会话。stdio 服务可能每次调用重启，不保证跨调用的进程内状态。见 [mcp_loader.py](../../../packages/harness/shikigen/core/mcp_loader.py) 与锁定 adapter `client.py`、`tools.py`。
- MCP Streamable HTTP 的默认客户端显式跟随重定向，与普通 HTTP 工具客户端默认不同；传输阶段超时也不等于全过程预算。见锁定 MCP `shared/_httpx_utils.py`、adapter `sessions.py`。
- MCP stdio SDK 尝试进程树清理，但 Windows Job Object 创建/分配失败会降级；不能承诺进程树一定全部终止。客户端停止等待也不代表远端已停止或撤销。见锁定 SDK `client/stdio/__init__.py`、`os/win32/utilities.py`、`shared/session.py`。
- adapter 成功返回保留转换后的内容块，`structuredContent` 放 artifact；错误分支未保留 `structuredContent`，音频块会抛未支持异常，资源块也不是完整原字段。因此完整结果需要在原始 MCP 返回层采集，不能仅依赖现有转换器。见锁定 adapter `tools.py`。
- SDK `ClientSession.call_tool()` 会按远端 `outputSchema` 检查成功的 `structuredContent`，不符合会抛异常；这是 MCP SDK 行为，与 HTTP 输出结构仅作参考的已确认规则分别处理。见锁定 SDK `client/session.py`。
- 普通 `BaseTool.ainvoke(args)` 没有 tool_call_id 时仅返回 content，省去 status/artifact；测试需要走完整结果入口。见锁定 langchain-core `tools/base.py`。

## 输入校验与后续验证

- BaseTool 对字典形式 args_schema 原样接收参数，不完成 JSON Schema 校验。jsonschema 已作为 MCP 间接依赖安装；直接使用时应声明为项目直接依赖。
- jsonschema 格式检查默认关闭；显式 FormatChecker 和部分可选依赖才提供检查能力。见 [jsonschema 官方文档](https://python-jsonschema.readthedocs.io/en/stable/validate/#validating-formats)。
- 仓库后端验证入口为 `uv run python -m unittest discover -s tests`；前端为 `pnpm test`、`pnpm build`。已有 [MCP loader 测试](../../../tests/test_mcp_loader.py)、[Run 取消测试](../../../tests/test_run_cancel.py)、[消息契约测试](../../../tests/test_message_contract.py) 可作参考，但尚未验证新工具执行、完整 MCP 原始返回或真实服务取消。

## config.json 保存接缝

- Python 默认读取 cwd 下的 config.json；桌面入口传入项目根配置文件的绝对路径。运行时仅保留解析后的 AppConfig，没有保留配置来源路径。见 [app_config.py](../../../packages/harness/shikigen/app_config.py)、[desktop.py](../../../app/desktop.py)、[backend.rs](../../../frontend/src-tauri/src/backend.rs)。
- AppConfig 与现有 MCP 子模型禁止额外字段；新增工具库字段需要显式扩展模型。现有 `mcp.servers` 按名字保存连接，并在启动时自动装配到当前 Agent，不是本轮工具库的独立连接集合。见 [app_config.py](../../../packages/harness/shikigen/app_config.py)、[composition.py](../../../packages/harness/shikigen/runtime/composition.py)。
- 配置加载会递归展开完整字符串 `$ENV_NAME`，运行时还会把部分路径变成绝对路径；直接回写 runtime.config 的 model_dump 会改变环境引用和原相对路径。新工具库中直接输入的字符串、schema 与来源数据需要避免被当作环境占位符展开；既有配置保存应基于原始 JSON 文档更新目标分组。
- 没有配置保存服务、热重载或多文件一致性协议。portalocker 已用于数据库运行锁，但尚未锁配置。新工具保存串行化、原子替换及代码文件一致性仍需实现。见 [data_ownership.py](../../../packages/harness/shikigen/runtime/data_ownership.py)。
- [.gitignore](../../../.gitignore) 已忽略 config.json，没有忽略 config/ 下的 Python 源码。代码文件的保存/删除和是否作为本地配置排除由后续生命周期方案决定。
- 桌面 CORS 当前仅允许 GET、POST；如果新 CRUD 使用 PUT/PATCH/DELETE，开发时应同步扩展允许方法。见 [desktop.py](../../../app/desktop.py)。
