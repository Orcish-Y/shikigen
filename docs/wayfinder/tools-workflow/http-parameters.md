# HTTP 参数与动态表单实现

2026-10-14，开发 ticket 02。页面继续遵循[工具原型规则](../../../frontend/design.md#工具页面原型)，执行与编辑行为来自[执行决议](tickets/003-execution-test-contract.resolution.md)、[页面决议](tickets/004-management-ui-lifecycle.resolution.md)和[HTTP 支持清单](tickets/005-openapi-import-scope.resolution.md#首版支持清单)。

HTTP 定义支持 GET、POST、PUT、PATCH、DELETE、HEAD、OPTIONS。`headers` 保存固定请求头，`parameters` 保存映射；每项包含 `location`（path/query/headers）、`input_name`（分组内输入名）、`name`（请求目标名），可选 `style` 和 `explode`。类型与必填性只保存在 `input_schema`。`inputs.body` 整体编码成 application/json，不拆成其他参数。

例如定义的地址为 `https://example.test/items/{item}`，映射为：

```json
[
  {"location":"path","input_name":"id","name":"item"},
  {"location":"query","input_name":"id","name":"id"},
  {"location":"query","input_name":"tags","name":"tags","explode":false}
]
```

对应输入 `{"path":{"id":"a/b"},"query":{"id":0,"tags":["a","b"]},"body":null}` 发送到 `/items/a%2Fb?id=0&tags=a%2Cb`，请求体为 JSON null。path 分组及其 id 必须在 schema 中声明为必填。path/header 只支持 simple 标量；query 支持 form 标量和标量数组，explode 默认 true 时使用重复键，false 时用逗号连接。固定 query 保留；固定和动态 header 重名、重复映射、未映射字段和悬空占位符在保存时诊断。

可选缺失不发送；path/query/header 显式 null 在执行前拒绝。空字符串、false 和 0 保留；query 空数组在重复键模式产生零项，在逗号模式发送空值。body 缺失时没有请求体；null、嵌套值和空容器按实际 JSON 编码。header 名称遵循 HTTP token，值要求可打印 ASCII；Host、Content-Length、Transfer-Encoding 和 Connection 由传输层维护。表单、文件、cookie、对象 query 和其他序列化不在当前支持范围。

输入 schema 明确支持 draft-07（未声明时的默认方言）和 2020-12，由对应 JSON Schema 校验器校验。支持普通类型与单一类型加 null、对象与数组、枚举/常量、数值/字符串/容器约束和无循环的本地 JSON Pointer 引用；未知方言、未知约束关键字、tuple 数组、循环/外部引用与组合结构明确拒绝。format、说明、示例和 default 保留为注解，执行不检查 format、不注入值、不转换类型。输出 schema 只描述结果 data，不验证或转换实际响应。

参数表格只编辑可准确表达的标量，修改字段时复制当前 schema 并保留其他内容；有额外类型约束时，表格中的类型修改锁定，复杂结构转高级 JSON。编辑 schema 会补齐新字段的同名映射，保留已有目标名和序列化；高级编辑可进一步修改映射。JSON 语法错误保留原文和解析位置，阻止保存。

测试参数由真实 rjsf 6.11.0 渲染；AJV 8.20.0 对两种方言使用独立实例，关闭 format、类型转换、默认注入和字段移除。初始输入为空；布尔和枚举保留未提供状态，minItems 不填占位。日期时间等 format 控件直接保留字符串，超范围数字明确拒绝，不因序列化变成 null。表单与 JSON 共用一个 inputs，保存同一工具、更新 schema 和切换模式保留输入；复杂结构或原输入不符合当前类型/枚举时提供 JSON 入口并说明原因。JSON 模式保留后端校验诊断，语法错误时阻止测试。

验证入口：`tests/test_tool_library_api.py` 通过公开 API 与本地 HTTP 服务检查真实请求；`frontend/tests/tool-management-dom.test.mjs` 操作真实 rjsf；`frontend/src-tauri/tests/tool_library_acceptance.py` 检查真实 WebView、嵌套输入、模式切换、schema 更新、POST 请求、主题和桌面/窄屏布局。[Ticket 03](tool-edit-drafts.md) 已将页面测试接入当前草稿；取消由后续 ticket 实现。

本票验证：后端全量 369 项（1 项跳过），审查修正后的工具 API 21 项；前端全量 311 项，最后的工具表单聚焦回归 16 项；Tauri 页面 2 项、Ruff、ty、TypeScript 和生产构建通过。前端完整回归以两个测试进程运行，避免原生验收同时启动时触发既有 Vite 端口测试的 20 秒时限。规范与规格审查各发现两项 P2，均修复并复核关闭。
