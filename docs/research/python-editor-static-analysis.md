# Python 源码编辑与前端静态分析调查

调查日期：2026-10-15。状态：已采用 CodeMirror 6 + Lezer，接入细节见 [Python 工具实现](../wayfinder/tools-workflow/python-tool-execution.md)。本文保留调查时的实现基线、上游能力、隔离验证结果与设计建议；不把编辑器高亮等同于 Python 编译校验。

## 建议

采用 **CodeMirror 6 + `@codemirror/lang-python` + Lezer 语法树**，替换当前源码 textarea。编辑时在本地提取 `main` 参数，生成参数预览和测试表单所需的临时 schema；保存、草稿测试和真实执行前继续由后端按实际 Python 解释器重新解析并生成权威结构。

这是本项目当前规模下的推荐取舍：本地反馈无需等待接口，同时保留 CPython 的完整编译检查。**Lezer 不是 CPython，不能承诺本地显示无错误就一定能够保存或执行。** 若要求编辑过程中也必须与后端完全一致，应另选匹配解释器版本的 Pyodide，并承担运行时资源、初始化和打包成本。

先不引入 Monaco + Pyright，也不为了参数预览在浏览器加载完整 Python 运行时。这个取舍来自下文能力和接入成本比较，属于本项目建议，并非上游性能基准结论。

## 调查基线（接入前）

- [`frontend/package.json`](../../frontend/package.json)：React 19、Vite 7、Tauri 2、rjsf 6.11.0；尚无代码编辑器依赖。
- 项目 `.python-version` 为 3.12，本次实际后端虚拟环境为 **Python 3.12.13**。
- [`ToolDefinitionForm.tsx`](../../frontend/src/components/tools/ToolDefinitionForm.tsx)：`source` 使用 `ui:widget: textarea`；源码变化后等待 250ms 请求 `parseSource`，并取消过期请求。成功结果同时更新参数预览和草稿的 `input_schema`；旧源码的结果不可继续视作有效。
- [`python_source.py`](../../packages/harness/shikigen/contracts/python_source.py)：先 `ast.parse`，再 `compile(tree, ..., "exec")`；检查唯一顶层同步 `main`、装饰器、签名、生成器入口；当前支持普通具名参数及 `str/int/float/bool` 注解。函数默认值决定可否省略，`None` 默认值不会自动把 `int` 变为 nullable。
- 当前默认表达式保留源码原文，后端只通过 `ast.literal_eval` 读取支持的标量字面量，不调用用户函数、不导入源码、不执行默认表达式。
- [ticket 06](../wayfinder/tools-workflow/implementation/06-python-schema-sync.md) 将继续增加容器、nullable、关键字参数、未知类型补齐和源码变更合并。前端提取器应有独立模块与可扩展的类型表示，避免把 05 的四种标量判断散落在组件中。

后端的 `compile` 有实际作用：Python 官方说明，`ast.parse` 成功仍可能在编译时抛出 `SyntaxError`，并不会执行编译阶段的作用域检查；例如顶层 `return` 能形成 AST，但不能编译为模块。[Python ast 文档](https://docs.python.org/3.12/library/ast.html#ast.parse)

## 上游能力与选型

| 路线 | 编辑、高亮 | 本地参数提取 | Python 校验边界 | 本项目建议 |
| --- | --- | --- | --- | --- |
| CodeMirror 6 + Lezer Python | Python 高亮、缩进、折叠、局部名称/关键字补全 | 可遍历语法树，需自行实现工具规则和 schema 映射 | 容错语法树，不等价于 CPython 的 parse + compile | 推荐用于即时编辑反馈和预览 |
| Monaco + Python tokenizer | 成熟编辑器；Python 基础注册与词法高亮 | tokenizer 本身不提供所需 AST，需再接解析器 | 不自动附带 Python 语法或类型检查 | 当前需求收益不足 |
| Monaco + Pyright/LSP | 可进一步提供诊断、补全、悬浮等语言服务 | 工具专有规则和 schema 生成仍需实现 | 需语言客户端、服务端或浏览器移植，仍非后端 CPython 编译器 | 未来确有 IDE 需求时再评估 |
| CodeMirror + Pyodide | 编辑器负责高亮，Python WASM 负责解析 | 可复用适合浏览器的 Python 静态解析模块 | 匹配 CPython 版本时最接近后端；版本和规则仍须统一 | 要求编辑期精确复核时的备选 |
| CodeMirror + web-tree-sitter | Tree-sitter 生成可增量更新的 CST | 可实现，但仍需工具规则 | 同为容错语法解析，不自动获得 CPython 编译检查 | 当前会多一套语法树及 WASM 资源链路 |

表中接入成本和适用性是基于下列官方能力作出的项目判断。候选包体已完成下文所述隔离测量，尚未完成真实 Tauri 集成后的启动性能对比。

### CodeMirror 与 Lezer

`@codemirror/lang-python` 的官方实现直接使用 `@lezer/python`，增加缩进、折叠、括号、注释配置和补全。它提供编辑所需语言支持，但未提供本项目的 `main` 协议或 JSON Schema 提取器。[语言包源码](https://github.com/codemirror/lang-python/blob/main/src/python.ts)

Lezer Python 的语法包含 `FunctionDefinition`、`ParamList`、`TypeDef`、`AssignOp`、`DecoratedStatement`、`Body` 以及默认值的表达式节点。可以按顶层与作用域遍历，定位参数和原文区间；不能用逗号分割字符串或正则表达式替代语法树。[Python grammar](https://github.com/lezer-parser/python/blob/main/src/python.grammar)

Lezer 默认会在错误处尝试恢复并继续生成树；`strict` 可以关闭恢复，但只是要求符合这套 grammar，不能增加 CPython 独有的编译检查。其解析源码明确区分恢复路径与严格模式的 `SyntaxError`。[LR 解析源码](https://github.com/lezer-parser/lr/blob/main/src/parse.ts)

CodeMirror 的 lint 模块负责将诊断显示为标记、提示和列表；诊断来源需要自行提供，可以遍历编辑器已有语法树实现。即装上 `python()` 后，仍需自己的错误节点扫描、工具契约检查和中文诊断。[官方 lint 示例](https://github.com/codemirror/website/blob/main/site/examples/lint/index.md)

维护状态需注意：CodeMirror/Lezer 的 GitHub 仓库于 2026-04-15 归档，README 明确说明迁移到 `code.haverbeke.berlin`，并非仅凭归档状态就能判断停止维护。本次 registry 隔离验证使用 `@lezer/python` **1.1.19**；GitHub 归档代码的版本可能滞后。后续锁定依赖时以实际包及其来源、完整性记录为准。[语言包迁移说明](https://github.com/codemirror/lang-python)、[grammar 迁移说明](https://github.com/lezer-parser/python)、[新语言包仓库](https://code.haverbeke.berlin/codemirror/lang-python)、[新 grammar 仓库](https://code.haverbeke.berlin/lezer/python)

### Monaco 与 Pyright

Monaco 当前 Python 定义导出的是语言配置及 Monarch 词法规则，注册文件将它作为基础语言加载；这不包含工具参数 AST 提取和 Python 编译器。[Python tokenizer](https://github.com/microsoft/monaco-editor/blob/main/src/languages/definitions/python/python.ts)、[Python 注册](https://github.com/microsoft/monaco-editor/blob/main/src/languages/definitions/python/register.ts)

Monaco 把补全、悬浮信息等能力交给 providers；VS Code 扩展不能直接装进浏览器 Monaco。官方亦未承诺移动端支持，因此本项目已有的窄屏验收仍需单独处理。[Monaco README](https://github.com/microsoft/monaco-editor#readme)

Pyright 官方 npm 包提供 `pyright` 与 `pyright-langserver` 两个 Node 入口，官方安装文档面向语言服务器和 CLI；接入 Monaco 需要语言客户端与运行语言服务的环境。存在浏览器移植不代表官方 Node 包能直接作为 Vite 浏览器依赖使用；本次不推荐把第三方移植引入为首版前提。[Pyright package](https://github.com/microsoft/pyright/blob/main/packages/pyright/package.json)、[官方安装说明](https://github.com/microsoft/pyright/blob/main/docs/installation.md)

### Pyodide 与 Python WASM

Pyodide 能在浏览器运行 CPython，因此理论上可在 Worker 内只调用固定的静态分析函数，把用户源码当作数据交给 `ast.parse` 和 `compile`，不运行用户源码。这种方案可减少前后端解析实现的重复，但需避免静态模块依赖 Pydantic、应用服务或操作系统特性；生成结果经 JSON 传回前端。这里的复用方式是方案推断，未完成本项目 PoC。

当前官方 stable 文档为 **314.0.7**；官方 changelog 记载 **314.0.0 于 2026-06-09 升级到 Python 3.14.2**。本项目当前后端实际为 3.12.13，因此不能默认最新版 Pyodide 与后端语义相同；应先明确工具运行解释器版本，再选可对应的发行版本。[Pyodide changelog](https://pyodide.org/en/stable/project/changelog.html#version-314-0-0)

部署至少涉及 loader、WASM、运行时 JavaScript、标准库 zip 和 lockfile。官方所述 200MB 以上是包含所有 vendored packages 的完整发行包；本需求所需核心文件已在下文单独实测。[官方部署说明](https://pyodide.org/en/stable/usage/downloading-and-deploying.html)

当前 Pyodide Worker 文档要求 module worker；Worker 用于避免同步 Python 工作阻塞界面。Tauri 打包后仍需验证本地资源 URL、CSP、WASM 加载、离线可用和冷启动，不能只在 Vite 开发服务器验证。[官方 Worker 文档](https://pyodide.org/en/stable/usage/webworker.html)

### web-tree-sitter

Tree-sitter 的定位也是编辑时增量生成 CST，即使存在语法错误也尽量产出有用结构。它不是 CPython 的 parse + compile 替代品。[官方介绍](https://tree-sitter.github.io/tree-sitter/)

官方 web binding 支持 Vite；需初始化 WASM runtime，并加载单独的语言 WASM。若采用 CodeMirror，其高亮已经使用 Lezer，额外引入 Tree-sitter 就要维护两套语法资源与结果；本需求尚无证据证明这层成本有必要。[官方 web binding](https://github.com/tree-sitter/tree-sitter/blob/master/lib/binding_web/README.md)

## 存储空间实测

测量日期：2026-10-15。以下为**文件逻辑大小**，1 MiB = 1,048,576 字节；不含文件系统分配单元开销、npm 缓存、应用原有资源、进程内存，也未计算安装器再次压缩。编辑器是独立最小页面的生产构建，不能直接当成接入现有应用后的精确增量。

| 方案 | 随应用分发的资源 | 说明 |
| --- | --- | --- |
| CodeMirror 6 + Lezer Python | **463,823 B，0.44 MiB（约 453 KiB）** | 编辑器、basicSetup、Python 高亮与直接调用的 Lezer parser |
| Monaco + Pyright | **已测小计 24,119,491 B，23.00 MiB** | Python 专用编辑器构建 4.45 MiB，加完整 Pyright npm 包 18.56 MiB；未含额外 Node 运行时和服务连接代码 |
| CodeMirror + Pyodide 314.0.7 | **13,995,030 B，13.35 MiB** | CodeMirror 0.44 MiB，加 Python 3.14.2 核心运行时 12.90 MiB |
| CodeMirror + Pyodide 0.27.7（Python 3.12 备选） | **14,311,929 B，13.65 MiB** | 该发行版为 Python 3.12.7，与当前后端 3.12.13 仍非完全相同版本 |

CodeMirror 版本为 `codemirror` 6.0.2、`@codemirror/lang-python` 6.2.1、`@lezer/python` 1.1.19；Monaco 为 0.57.0，Pyright 为 1.1.414。构建使用项目现有 Vite 7.3.6、esbuild 压缩、无 source map，Node 24.21.0。CodeMirror 包含 basicSetup 的行号、历史、搜索、折叠、补全等基础功能；尚未包含本项目自定义参数提取器、诊断规则及 React/rjsf 接入代码。

Monaco 保留默认编辑器功能、内置 LSP 客户端导出、Python tokenizer、编辑器 Worker、CSS 与字体，排除其他语言定义及 JSON/HTML/CSS/TypeScript 语言服务。输出构成：主 JS 4,054,301 B、Worker 275,493 B、CSS 175,373 B、字体 153,228 B、Python tokenizer 3,720 B、HTML 256 B。该构建验证资源体积，未完成与 Pyright 的可用连接；Monaco 的 Worker 接入方式参考[官方 ESM 集成说明](https://github.com/microsoft/monaco-editor/blob/main/docs/integrate-esm.md)。

Pyright 按官方 npm 包完整保留计算，包含随包提供的 stubs 和 source maps，未做手工裁剪。官方包通过 Node 启动 `pyright-langserver`，不能把上表小计当作浏览器内完整语言服务的体积；若服务在后端运行，客户端仅承担 Monaco 约 4.45 MiB，Pyright 占用服务端磁盘。若桌面应用另行捆绑 Node，该运行时大小还需另计。[官方 package.json](https://github.com/microsoft/pyright/blob/main/packages/pyright/package.json)

Pyodide 314.0.7 的 12.90 MiB 来自五个核心文件：`pyodide.mjs` 17,931 B、`pyodide.asm.mjs` 1,250,344 B、`pyodide.asm.wasm` 9,598,218 B、`python_stdlib.zip` 2,545,637 B、`pyodide-lock.json` 119,077 B。0.27.7 的对应资源共 13,848,106 B（13.21 MiB）。两版均在禁用网络 fetch 的 Node 环境中完成 `loadPyodide`、`import ast`、`ast.parse` 和 `compile`，没有加载第三方 Python 包。该验证说明静态分析不必带全套 NumPy/Pandas 等依赖；尚未证明 Tauri WebView 的实际启动体验。核心文件范围依据[官方部署清单](https://pyodide.org/en/stable/usage/downloading-and-deploying.html)。

开发机 `node_modules` 是另一种口径：CodeMirror 及依赖 **3.35 MiB**；Monaco 及依赖 **99.60 MiB**；再加 Pyright 为 **118.16 MiB**。Monaco npm 包含多套发布产物和其他语言，不能用这个开发依赖占用替代上表生产文件大小。

网络传输也应单列：按文件 gzip 压缩，CodeMirror 构建约 **152 KiB**、Monaco 构建约 **1.17 MiB**；实际 CDN gzip 响应中的 Pyodide 核心分别约 **6.04 MiB**（314.0.7）和 **5.46 MiB**（0.27.7），均未加编辑器。gzip 数字不代表安装后的文件占用。

原始证据和复现脚本位于本机 `.scratch/tools-workflow/research/python-storage/`：`editor-sizes.json`、`bundle-probe/measure.mjs`、`bundle-probe/package-lock.json`、`pyodide-*.json`、`pyodide-*-bootstrap.json`。这些是隔离样本的实测，所有安装与构建均在 scratch 目录，没有改动项目依赖或锁文件；目录受 Git 忽略，表中的测量结论保留在本文。

## 隔离验证

主调查在项目 scratch 目录下载并按 registry SHA512 核对独立 npm 包，没有安装到 frontend、没有修改锁文件。验证使用 `@lezer/python` 1.1.19，对同一组 19 段源码运行 Lezer 和项目现有后端解析器。

记录在本机 `.scratch/tools-workflow/research/python-parser/`：`packages.json`、`cases.json`、`probe.mjs`、`backend-results.json`、`lezer-results.json`。这些是本仓库此次实测证据，不是上游保证，目录受 Git 忽略。

| 样例 | Lezer 观察 | 现有后端观察 | 设计含义 |
| --- | --- | --- | --- |
| 标量参数、多行注释、带逗号字符串、负数、True/None | 能定位 main 及参数/注解/默认表达式节点 | 解析成功并生成 schema | 可以实现本地参数预览 |
| 缺失右括号 | 有错误节点 | `python_syntax` | 可给编辑期语法提示，错误文案无需假装来自 CPython |
| 重复参数 | 无错误节点 | `python_syntax` | 需要额外参数规则或后端兜底 |
| 默认参数后接必填参数 | 无错误节点 | `python_syntax` | 有树不代表签名合法 |
| 顶层 return；函数内不在循环中的 break | 无错误节点 | `python_syntax` | 编译语义不能只靠错误节点检查 |
| 重复 main、只有嵌套 main、async main、生成器 main | 可以形成树 | `python_entry` | 属于工具协议，必须自己实现 |
| Optional/容器注解、仅关键字参数 | 可形成结构 | 当前 05 拒绝，分别为 annotation/signature 错误 | grammar 支持不代表产品已支持；按 06 逐项解锁 |

默认值还有跨语言差异：本次 `9007199254740993` 在 Python 中可保持整数值，而 JavaScript `Number` 会变为 `9007199254740992`；Python raw string、转义、相邻字符串拼接和十六进制字面量也不能交给 JSON 解析器代替 Python 字面量规则。前端首版只精确保留 `default_expression`，不执行、不盲目转成 JavaScript 数值，不将默认值自动填入实际调用输入。

## 最小接入设计

1. **保持数据类型。** `source` 的 JSON Schema 继续为 `type: string`；只将 rjsf `ui:widget` 换成 `PythonSourceEditor`。rjsf 支持为 string 注册自定义 widget，并通过 `value/onChange`、`disabled/readonly`、焦点回调与表单连接。[rjsf 6.11 自定义 widget](https://rjsf-team.github.io/react-jsonschema-form/docs/advanced-customization/custom-widgets-fields/) 调查时 [`SchemaForm.tsx`](../../frontend/src/components/tools/SchemaForm.tsx) 会覆盖传入的 `props.widgets`；本次已合并注册表，使命名 widget 可以透传。
2. **编辑器与解析器分离。** `PythonSourceEditor` 用 React ref 管理 CodeMirror 的创建、更新和销毁，负责高亮、行号、缩进、撤销、错误标记；`analyzePythonSource` 是纯 TypeScript 模块，接收完整源码并返回诊断、参数元信息及临时 schema。入口唯一性必须基于整份源码，不能只分析视口或尚未完成的编辑器局部树；先独立全量 parse，有性能证据后再增量或 Worker。先不依赖额外 React wrapper，降低 wrapper 与 React 19 的兼容面；该接入方式仍需实际验证。
3. **统一一次分析结果。** 源码变化立即使旧分析失效，再短防抖执行本地分析；诊断和参数表复用同一结果。每份结果带源码 revision，异步 Worker 或懒加载完成时只接收最新 revision。没有完整可信参数结构时不继续用旧 schema 测试。`analysis` 与可编辑草稿分开：本地派生 schema 不再写回草稿并触发 `onEdited`，否则后端包含字面量默认值、本地仅保留表达式时，刚重读详情就可能错误显示未保存。05 的 dirty 比较只计源码和管理字段，测试表单从当前 analysis 读取 schema；06 再纳入用户补充约束。
4. **明确本地校验范围。** 扫描错误节点；只统计模块直接声明的 main；处理 decorated/async；检查受支持签名及重复名、默认参数顺序；生成器扫描跳过内层函数与 lambda。通过语法树识别注解与默认值表达式，不对正文做全量类型检查，不执行表达式。
5. **区分参数元信息。** 参数记录至少有 `name`、参数类别、类型表达式/识别状态、`required`、`default_expression`、源码区间。类型识别层与 schema 输出层分开；06 再添加容器、nullable、kwonly、kwargs 与用户补充合并，保持省略、null、默认表达式为不同概念。
6. **明确权威来源。** 本地 schema 只服务预览和填写；保存/测试提交源码及用户管理字段，后端从源码重生不可编辑的名称、类型、必填性。05 不要求前端把所有派生 schema（尤其解码默认值）反传后再与后端严格相等；06 则单独提交或明确识别用户补充结构，由后端验证合并边界。需配套修改当前草稿契约，不能只删除远程调用。
7. **保留不确定状态。** Lezer 版本不认识的合法新语法与确定不合法应分开处理，不能一律作为不可保存；遇到语法支持边界仍允许触发后端权威校验，并将后端错误留在当前草稿。界面可写“本地检查完成”，不写“Python 校验通过”。
8. **移除编辑期网络依赖。** 完成上述步骤及一致性验证后，取消每次输入触发的 `parseSource` 请求。再搜索 `parse_python` 的其他调用方：没有需要时删除独立预览接口，有需要则保留为权威分析能力。后端保存与测试所用的解析函数必须保留。

若将后端错误标记到源码中，建议返回结构化 `code/message/line/column/end_line/end_column`，并明确坐标单位；Python 与 JavaScript 的字符/字节/UTF-16 偏移不能直接混用。此项属于拟议接口改进，当前后端只有错误消息字符串。

## 实施时的验收范围

- 共享源码样例覆盖后端既有入口/签名规则及本次发现的 grammar 差异；比较参数名、类型、必填性、默认表达式和错误类别，不要求前端复制全部 CPython 英文报错文本。
- 加入注释、多行、Unicode、CRLF、字符串拼接/转义、非十进制和大整数、嵌套函数/生成器、装饰器、异常不完整输入；确保分析过程不产生用户源码副作用。
- 预览和动态表单随源码同步；无效/未完成输入不复用旧结构；快速切换工具、编辑中改其他字段、撤销重做、重新读取草稿不丢光标/源码，保存成功但详情读取失败继续沿用既定保存状态规则。
- 验证 CodeMirror 的中文 IME、Tab 与表单焦点、键盘可访问性、只读/禁用、1440 与 390 宽度、原型布局，以及真实 Tauri WebView 打包运行。
- 量测接入后的实际构建增量、编辑器首次打开、不同源码长度下的分析耗时；超过交互预算再将分析放入 Web Worker。上文仅有独立样本的文件体积，没有足够数据承诺真实应用的启动或分析毫秒数。
- 后端接口被直接调用时仍执行全部解析规则，客户端派生 schema 不可绕过工具契约。若将来采用 Pyodide，另测解释器版本、冷启动、离线资源和复用解析函数的一致性。

## 待决策

推荐先落实“高亮编辑器 + 本地参数预览 + 保存/测试权威复核”。若产品要求在编辑期间就完全复制后端 CPython 的完整语法/编译结果，再为匹配版本的 Pyodide 做单独 PoC 和体积/初始化实测；不要用 Lezer 无错误节点来替代这个承诺。
