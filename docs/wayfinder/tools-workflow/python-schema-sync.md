# Python 类型补齐与源码变更同步

2026-10-18，ticket 06。页面继续遵循[工具页原型](../../../frontend/design.md#工具页面原型)，参数契约依据[执行决议](tickets/003-execution-test-contract.resolution.md)。

源码静态解析与最终输入结构校验分开。`parse_python_source` 提取当前 main 的签名和已识别注解，未识别部分保留为空结构；`prepare_python_input_schema(source, supplied)` 在保存、草稿测试和已保存执行时统一复核最终 schema。它返回独立副本，不修改调用方传入的结构，也不执行或导入源码。只有最终 `input_schema` 持久化，不保存解析参数表、编辑器诊断或变更记录。

支持普通具名参数、仅关键字参数、默认参数和 `**kwargs`，以及 str/int/float/bool、普通 list/dict、list[T]、dict[str, T]、T | None、Optional[T]。常见 typing 限定名和字符串注解也静态识别。只支持字符串字典键；不解析任意导入别名、自定义类型或对象构造。仅位置参数、*args、异步、生成器、装饰器及类方法入口继续明确拒绝。函数默认值决定可省略性，与允许 null 分开；测试输入不自动注入 schema 默认值。

无注解和未知注解需要显式选择 JSON 类型。已识别的外层类型只读；普通容器或未知容器元素需要补充内部类型与结构，或用 `items: true` / `additionalProperties: true` 明确开放。对象也可声明业务 properties 并用 `additionalProperties: false` 关闭额外字段。未知注解不会自动变为字符串或任意 JSON；未知类型的 null 许可仍来自 Optional 或 `| None`。自定义对象仅接收所选 schema 对应的原始 JSON 数据，不自动实例化。

高级 JSON 可以补充说明、示例、枚举、范围、嵌套约束和本地引用。它不能删除、重命名、改变源码参数的类型、必填性或 null 许可；容器内已识别的元素和值类型也受保护。没有 `**kwargs` 时不允许新增业务参数或开启顶层附加属性。有 `**kwargs` 时，额外字段必须由 schema 声明或显式开放；其注解（如 `**extras: int`）约束每一个额外业务字段。顶层参数直接声明，不通过 `$ref` 或 patternProperties 改写；嵌套字段可使用既有 JSON Schema 子集及对象目标的本地引用。开放容器的布尔 schema 直接填写 true/false，页面暂不支持布尔引用目标。

源码编辑后 Lezer 自动重新分析，并把当前 schema 与新签名同步。同名兼容属性保留类型选择、说明及业务约束；新未知字段保持待补。删除、改名、必填性变化和不兼容类型变化显示在预览区，改名按删除与新增处理。不兼容补充从候选 schema 中移除，但原内容保留在可展开的变更记录中；用户确认变更、补齐新结构后才能保存和测试。引用字段在兼容变化中保留原引用，冲突时明确提示重新补齐。

源码或高级 JSON 失败保留当前源码、schema 原文和错误信息，阻止沿用旧结构执行。源码恢复有效后继续从最近可解析签名同步；高级 JSON 的无效原文不会因源码变化而被覆盖。只保留编辑期间的变更记录，重新读取已保存详情后不再显示旧记录。

右侧动态测试表单使用当前有效 schema，schema 变化不重置实际输入。无法安全呈现的 nullable、引用等结构使用 JSON 参数；不匹配值及已删除字段保留原样并显示诊断，由后端统一校验，页面不暗中删除或转换。原有工具 ID、相对源码文件管理、先写新源码再提交配置引用的顺序，以及草稿测试不保存的行为保持一致。

源码解析接口没有恢复。正常页面提交源码与最终 schema；Lezer 无法识别语法或转义注解时，原有显式「交给后端校验」入口仍可使用，提交时去掉未经确认的结构，由后端重新解析，不能复用旧结构执行。含有需人工补充参数的源码仍须先补齐；后端不会把缺失补充视作开放类型。

验证入口：`tests/test_python_tool_api.py` 使用公开 API 和真实子进程，`tests/fixtures/python_source_cases.json` 的 33 段源码同时覆盖后端与 Lezer，`frontend/tests/tool-management-dom.test.mjs` 使用真实 RJSF、CodeMirror 和表单，`frontend/src-tauri/tests/tool_library_acceptance.py` 覆盖 Windows WebView 及 1440/390 布局。

## 验证结果

后端全量 408 项通过（1 项跳过）；前端全量 369 项全部通过，包括 37 项工具页面交互。TypeScript 与 Vite 生产构建、本票 Python 文件的 ty、Ruff 和补丁检查通过。全库 ty 仍报告 263 项诊断，涉及 28 个本票未修改的文件；没有诊断落在本票修改的 Python 文件中。

真实 Windows WebView 的原有 Python 编辑器与本票类型补齐用例均通过，最终构建又单独复测类型补齐与同步流程。覆盖待补阻断、已识别类型只读、高级约束保留、草稿不保存、保存重读、冲突确认及实际输入保留；1440/390 截图已查看，保留原型的双栏／窄屏单栏组织和局部表格滚动。

本地日志：`.scratch/tools-workflow/ticket06-backend-full.log`、`ticket06-frontend-full-final.log`、`ticket06-dom-final.log`、`ticket06-build-final.log`、`ticket06-native-final.log`。截图位于 `verification/native/test_python_type_completion_schema_sync_and_retained_inputs/`。首次后端全量运行在既有桌面进程测试挂起，单独验证通过后，使用附带进度及超时堆栈的运行器完整重跑并通过；没有遗留失败。

## 审查

Standards：0 项未解决违规、0 项未解决建议。注解名称识别的重复逻辑已提取；共享 AJV 校验从 UI 移至 `schema-validation.ts`，不保留旧导出别名。

Spec：0 项未解决发现。审查发现合法 JSON 中无效 schema（如 `required: 2`）会在源码同步时抛异常，现已先验证 schema，再决定是否同步；RJSF 克隆相同数据时也保留用户 JSON 原文。已通过失败复现、DOM 回归和独立复核关闭。显式后端校验的草稿测试同样去掉未经确认的旧 schema，并由当前源码重新生成。
