# Python 工具：源码、参数与本机执行

2026-10-15，ticket 05；2026-10-18 已由 ticket 06 扩展[类型补齐与源码变更同步](python-schema-sync.md)。页面继续参照[工具页面原型](../../../frontend/design.md#工具页面原型)，执行依据[执行决议](tickets/003-execution-test-contract.resolution.md)。以下实现与历史验证记录按各自日期阅读，当前 schema 补充和同步规则以 ticket 06 记录为准。

工具页「接入工具」旁的类型菜单可新建 Python 工具。配置卡片使用 CodeMirror 6 编辑源码，提供 Python 高亮、行号、四空格缩进、撤销重做和错误标记；结构卡片展示只读参数预览，右侧 rjsf 按当前有效 schema 收集实际输入。Tab 缩进，Esc 后按 Tab 可以离开编辑器。布局继续参照原型，不改变类型 tab、隐藏禁用工具、草稿离开确认和保存后读取详情的行为。

编辑阶段由 Lezer 分析完整模块，在本地检查入口与支持的签名并提取参数，不请求源码解析接口。分析结果与草稿分开，打开工具或重读详情不会因重新分析而变为未保存；源码更改立即使旧分析失效。默认值仅保留表达式原文，不在 JavaScript 中求值或转换，也不填入实际测试输入。保存和草稿测试提交源码及管理字段，不提交本地派生的 `input_schema`；后端重新生成权威 schema，保留原有标量默认值及校验规则。

本地明确的入口、签名或注解错误阻止保存和测试。Lezer 不能替代 CPython 的语法与编译校验：它不认识的语法或复杂字符串注解提供「交给后端校验」入口；用户选择后可以提交保存，测试表单切换为 JSON，仍不复用旧结构。源码再次修改会撤销该选择。所有保存、测试及执行仍由后端按实际解释器执行 `ast.parse`、`compile` 和工具协议检查，失败时保留源码及实际输入。业务返回和 stdout/stderr 分开显示，完整结果可查看、复制。

当前固定唯一的顶层同步 `main`，可以包含辅助函数。支持普通具名参数、`str/int/float/bool`（包括这些名字的字符串注解）和函数默认值。缺少注解、未知/容器/nullable 注解、仅关键字参数、`**kwargs` 由 06 完成；当前明确拒绝。仅位置参数、`*args`、异步、生成器和装饰器入口也明确诊断。AST 解析及编译仅检查源码，不执行/import 用户代码，不 eval 注解或默认表达式。可识别的标量字面默认值和默认表达式用于预览；函数有默认值决定能否省略，不使输入自动允许 null。

API 使用既有 CRUD 和草稿测试入口，另有：

| 接口 | 行为 |
| --- | --- |
| `GET /api/tools/schema/python` | Python 管理表单 schema，包含源码录入字段 |
| 创建/更新 Python 定义 | 接收 `source`，重新解析并生成 `input_schema`；外部调用方如显式提交 schema 仍须与解析结果一致；`code_path` 只由系统管理 |
| `GET /api/tools/{id}` | Python 详情从文件读取并附带 `source`；列表与持久定义仅含 `code_path` |

Python 的编辑保存和草稿测试都要求显式提交 `kind: "python"` 与非空 `source`；缺字段、null 或空白源码直接失败，不从已保存定义、schema 或源码文件补齐执行配置。`_prepare_python_payload(payload)` 是同步解析步骤，不接收旧定义，不读写文件，不修改传入的草稿。已有记录只参与外层的编辑目标检查、同一 ID 不可变更类型、字段修改限制，以及 ID、创建时间等系统字段的维护；配置版本冲突仍在保存时检查。

草稿测试通过内存源码快照执行，不写受管理源码文件或配置，也不依赖旧 `code_path`。构造持久定义模型时暂用内部路径占位，保存时才写入当前源码并替换为实际生成路径，占位不会提交到配置。即使旧源码文件缺失，完整新草稿仍可测试或保存；专门测试已保存工具的入口则继续显式读取其源码文件。

2026-10-18 验证：执行器与 HTTP/Python 工具 API 共 51 项通过，覆盖缺失/空源码、缺失类型、旧文件缺失时使用新源码测试与保存、草稿不落盘，以及编辑目标和系统字段限制；Ruff、ty 与 diff 检查通过。日志为 `.scratch/tools-workflow/python-draft-current-payload-*.log`。

原编辑期专用的 `POST /api/tools/python/parse` 及前端 client 方法已移除；后端静态解析函数继续由保存、测试和执行使用。前端模块为 [`python-source.ts`](../../../frontend/src/python-source.ts) 与 [`PythonSourceEditor.tsx`](../../../frontend/src/components/tools/PythonSourceEditor.tsx)；RJSF 保持 `source` 为 string，通过自定义 widget 呈现编辑器。选型、能力边界和体积测量见[调查文档](../../research/python-editor-static-analysis.md)。后续 06 应扩展独立参数分析模块与结构合并规则。

例如源码 `def main(quantity: int, price: float = 2.5): return quantity * price` 对应输入 `{"quantity": 4}`，执行 `main(**inputs)` 得到 `10.0`。后端先按 JSON Schema 校验，不转换输入或注入 schema 默认值。源码再次静态核对后，已授权的子进程检查实际同步入口并使用 `inspect.signature(...).bind(**inputs)` 核对参数。

源码写入实际配置文件旁的 `config/tools/<tool-id>-<revision>.py`。路径以配置目录为基准，拒绝绝对路径、上级路径和符号链接，缺失/不可读文件明确失败。保存先写入完整新文件、flush/fsync 并关闭，再原子提交引用它的配置；提交前旧文件保留。成功后及删除时，只清理该目录内符合生成名称且不再被引用的文件，保留用户示例文件。源码不内联到持久配置，不另存持久草稿或参数表。`.gitignore` 忽略本地 `config/tools/`；需要分享的示例请单独保存。

每次调用复制取得的完整源码，在独立临时目录启动后端 `sys.executable` 对应的解释器，使用标准库及当前环境已安装依赖。子进程标准输入关闭，避免继承桌面控制通道；Windows 隐藏子进程控制台。结束后回收进程并清理临时目录，不安装依赖、不创建专属环境。这是本机权限执行，不是安全沙箱。整体执行预算沿用每工具 1–300 秒；超时终止并回收本次子进程，保留可取得的退出码和调试输出。

返回值必须是严格 JSON：对象键为字符串，支持对象、数组、字符串、有限数字、布尔和 null，保留类型；tuple、set、自定义对象、NaN/Infinity 等明确失败。业务返回 UTF-8 JSON 超过 1 MiB 时失败。返回协议使用单独结果文件，stdout/stderr 管道只承载调试输出，合计保留最后 64 KiB，并记录各通道截断标记与进程退出码。运行异常、入口/绑定错误、非法返回、异常退出和超限使用不同错误码。

后续 06 扩展类型补齐与源码变更同步；12 完成页面取消控制和取消生命周期；13 补充外部修改、文件读取/清理协调和多文件一致性的异常场景。当前已读取的执行源码是内存副本，但不承诺派生进程树全部停止。

## 执行适配器装配（2026-10-16）

`ToolExecutor` 只接收 `kind -> ToolAdapter` 映射，负责启用检查、输入校验、执行预算、取消和统一结果。HTTP/Python 适配器在 `ToolLibrary` 的装配处创建；`PythonSourceStore` 由工具库的 `python_source_store` 属性持有，负责加载和保存源码，`PythonAdapter` 不再接收文件存储依赖。统一从 `persistence/python_source_store.py` 导入，不保留旧模块或属性别名。执行器不创建具体适配器，也不按适配器类执行 `isinstance` 分支。

2026-10-18 调整：持久化定义与执行对象分开。公共接口在 [`contracts/tool_execution.py`](../../../packages/harness/shikigen/contracts/tool_execution.py)：`ToolExecution` 携带定义，`PythonToolExecution` 另外携带必填的源码快照，不为所有工具增加可选的 Python 字段。`ToolExecutor.execute(load, inputs, *, manual_test=False)` 由 `load()` 获得完整执行对象，不再单独接收 `source`。每次执行已保存工具时，工具库重新读取定义及源码后构造对象；已保存工具测试共用这一步。草稿测试直接使用当前提交的源码构造对象，不读取旧文件、不保存草稿。

适配器统一实现 `execute(execution, inputs, *, context)`。Python 适配器只消费执行对象中的源码，并核对参数结构，不回退到文件读取；加载完成后文件发生修改也不会改变本次执行，后续调用重新加载。`ToolExecutionContext` 每次调用独立创建，仅携带可写执行信息，不携带源码；适配器在清理时写入的信息仍可用于超时或取消结果。HTTP 传输错误在 HTTP 适配器内转换为原有 `transport` 错误。源码加载属于执行前准备，执行预算继续覆盖适配器启动、业务执行及读取结果。

工具实现按类型归入 `tools/`：HTTP 请求适配器在 [`tools/http/execution.py`](../../../packages/harness/shikigen/tools/http/execution.py)，Python 适配器及其子进程入口分别在 [`tools/python/execution.py`](../../../packages/harness/shikigen/tools/python/execution.py) 和 [`tools/python/worker.py`](../../../packages/harness/shikigen/tools/python/worker.py)。通用执行器位于 `tools/executor.py`，源码文件存取位于 [`persistence/python_source_store.py`](../../../packages/harness/shikigen/persistence/python_source_store.py)，执行模块不反向依赖 runtime。MCP 会话提供者在装配时注入对应适配器，再登记映射；连接配置和会话管理不进入 `ToolExecutor` 的构造函数或工具定义。目录职责见[工具模块布局](tool-module-layout.md)。

装配调整时的验证记录：执行器接口 7 项与既有 HTTP/Python 工具 API 40 项全部通过，覆盖自定义适配器登记、调用上下文隔离、输入和禁用检查、超时与取消清理信息、HTTP 传输错误、真实请求和 Python 子进程。Ruff、ty 与 diff 检查通过。日志为 `.scratch/tools-workflow/adapter-injection-*.log`。

执行对象调整验证：执行器、HTTP/Python 工具 API 及包导入共 55 项通过，覆盖完整执行对象透传、上下文隔离、缺少 Python 源码执行对象时明确失败、加载后文件变化仍使用本次快照，以及既有草稿、保存、超时和取消行为。Ruff、ty 与 diff 检查通过。日志为 `.scratch/tools-workflow/tool-execution-object-tests.log`。

验证入口：`tests/test_python_tool_api.py`（临时配置、公开 API、真实子进程），`frontend/tests/tool-management-dom.test.mjs`（真实 rjsf），`frontend/src-tauri/tests/tool_library_acceptance.py`（真实 Windows WebView、1440/390 布局）。本票测试日志保存在本地 `.scratch/tools-workflow/05-*.log`。


ticket 05 原始验证记录：后端全量 387 项通过（1 项跳过）；审查及桌面进程修正后的 Python API 8 项通过。前端全量 325 项中 324 项通过，Vite 端口生命周期用例在并行构建时超过原有 20 秒限时；构建结束后单独复跑对应文件 9 项全部通过。TypeScript、Vite 生产构建、ty、Ruff 和 diff 检查通过。工具页专属入口的 7 项真实桌面验收通过，覆盖源码、默认参数省略、业务返回/调试输出、保存重读、无效源码阻断，以及 1440/390 源码、预览和结果布局；截图已逐一查看。

## Standards

0 项规范违规、0 项未解决的维护性发现。原发现的执行模块反向依赖已通过提取公共 `contracts/tool_results.py` 解决并复核关闭。

## Spec

0 项未解决发现。原发现的多字节调试输出截断可能超限，已以真实子进程复现 65538 字节案例，修正为丢弃截断边界的不完整 UTF-8 字符，并通过公开 API 回归和复核。完整取消及外部文件协调继续由 12/13 完成。

## CodeMirror 接入验证（2026-10-15）

本次相关前端 68 项通过：本地分析/工具草稿/后端 client 37 项，工具页真实 RJSF 与 CodeMirror 交互 31 项；CRLF 诊断映射修正后单独复跑编辑器用例通过。交互测试使用现有 esbuild 打包同一份测试入口后执行，避免本环境中表单和图标包逐文件加载耗时；保留真实组件与编辑器，没有替换为测试 stub。后端 Python/HTTP 工具 API 及共享源码契约共 40 项通过。`tests/fixtures/python_source_cases.json` 的 29 段源码同时用于 Lezer 与后端测试，明确保留“编辑器语法树可接受、CPython 编译拒绝”的边界案例。

TypeScript、Vite 生产构建、ty、Ruff 与 diff 检查通过。桌面验收覆盖 Python 工具完整创建、编辑、测试、保存重读、中文组合输入、四空格 Tab 缩进、撤销重做、Esc/Tab 离开编辑器、长行局部滚动、错误阻断与原输入保留，以及 1440/390 下源码、预览和结果布局。日志在 `.scratch/tools-workflow/codemirror-*.log`，截图沿用 `verification/native/test_python_source_preview_named_inputs_and_separate_debug_output/`。
