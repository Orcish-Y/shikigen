# OpenAPI 基础导入与工具编辑

10 号票的实现记录。工具页沿用 [demo 原型](../../../design/demo-工具.html) 和 [前端规则](../../../frontend/design.md#工具页面原型)：64px 主导航、256px 工具侧栏、48px 操作栏、概览和 7:5 双栏；窄屏堆叠，保存操作保持可见。

## 入口和边界

工具侧栏「选择接入类型 → 导入 OpenAPI 文档」支持上传或粘贴单份 JSON／YAML，识别 3.0.x／3.1.x；不下载文档 URL，不支持 Swagger 2.0。上传只读取文件，点击解析才生成预览；解析、预览、保存不会调用业务接口。手工 HTTP／Python 创建和 MCP 接入继续可用。

本票只转换内联普通无认证请求。实际请求使用的 schema、parameter、requestBody 或 path item 引用、认证要求、复杂组合及未支持序列化会阻止对应项导入；不删约束后继续保存。未选中的未支持项不阻止普通接口保存。内部引用、认证导入及完整兼容诊断由 11 号票继续完成。凭据沿用用户决定：不引入 credential 管理或隐藏协议。

解析与转换独立放在 `shikigen/tools/http/openapi_import.py`，与 `tools/builtin` 的 Agent 内置工具及 HTTP 执行适配器分别存放；目录职责见[工具模块布局](tool-module-layout.md)。使用显式 PyYAML 依赖和安全加载器；重复键、非 JSON 值、解析和版本错误明确返回文档错误。API 文档上限 2,000,000 字符，上传文件限制 2 MB。

## 生成同一个 HTTP 定义

- 方法、路径取自 operation；前端从 operationId 或方法／路径生成合法调用名称，避开现有、内置工具及同次预览候选。页面名称来自 summary，用途来自 description 或 summary；缺失时补充，用户可编辑。
- 服务器按 operation > path > 文档级读取，保留多个候选。相对地址和变量保留为待补配置，不猜宿主或默认变量；补齐绝对 HTTP(S) 地址后保存。服务器模板占位符不能借同名业务 path 参数绕过补齐。
- 参数按 `(in, name)` 合并，接口级覆盖路径级；同层重复诊断，请求头按大小写不敏感检查。path／query／headers 保持原名、必填及序列化；支持标量、query 标量数组 form/explode。body 选择 application/json，保留嵌套对象、数组和整个 body 的必填性。
- 输入由 `input_schema` 唯一声明，映射只保存位置与序列化，复用统一 HTTP 校验。3.0 nullable 和布尔 exclusive 范围转换为既有 2020-12 方言，3.1 保留普通类型加 null；说明、示例和常用约束保留。
- 每项生成现有 `HttpToolDefinition`，没有 openapi 运行类型。可选 `openapi_source` 保存版本／info、实际服务器、路径级配置、所选 operation；结构卡片中折叠查看。它是导入记录，不覆盖后续 HTTP 配置；普通更新未提交此元数据时保留来源。
- 单一明确的 JSON 成功输出预填 `output_schema`；多个成功状态的相同结构也可预填。不确定、复杂或多种不同输出留空并解释；实际调用不按输出 schema 强制校验或转换。

优先级、参数覆盖和序列化依据 [OpenAPI 3.0.4](https://spec.openapis.org/oas/v3.0.4.html) 与 [3.1.2](https://spec.openapis.org/oas/v3.1.2.html)；这是本项目子集，不代表完整兼容。

## 公开 API 和保存行为

`POST /api/tools/openapi/preview` 接收 `{document: string}`，返回 `{data: {openapi, title, operations}}`。每项包含文档内 `key`（方法＋路径）、方法／路径、`name_hint`、服务器候选、待编辑 `definition`、阻止导入的 `errors`、输出提示 `warnings` 和来源初始缺配置原因 `configuration_errors`。名称候选在前端生成；API 调用方提交确认的合法名称。

`POST /api/tools/openapi/imports` 接收 `{document, tools: [{operation_key, definition}]}`，成功返回 201 和 `{data: [{id}]}`。后端重新解析核对所选项是否受支持，从文档补入来源，不信任客户端取消错误。所有所选定义按 HTTP 模型验证，在同一工具库锁内准备新工具、检查名称，一次提交。任一项非法、重名或写入冲突都不创建一半。

再次导入始终新建 ID；名称必须唯一，旧定义保持。导入后通过既有详情读取、更新、草稿测试、执行与删除接口管理；普通编辑保持 ID。

文档、勾选和预览修改只在内存保存，不写 localStorage。切换预览保留编辑；重新解析替换预览前确认；离开支持保存并离开、放弃、继续编辑。保存拒绝保留草稿；成功但列表／详情读取失败保留已保存 ID，只重读；响应丢失锁住再次导入，提供显式放弃草稿并重读，不自动重试保存。

## 验证入口

- `tests/test_openapi_import_api.py`：公开 API 和本地 HTTP 服务，覆盖两种格式／版本、名称参数分离、服务器优先级／候选与变量、参数覆盖、嵌套 body、query 数组、未支持项隔离、整批失败、编辑、实际响应和再次导入。
- `frontend/tests/openapi-import-dom.test.mjs`：上传／粘贴、补配置、候选地址、勾选、切换保留、保存失败、保存后读取失败、不确定响应和脏草稿离开。
- `frontend/src-tauri/tests/tool_library_acceptance.py` 中 `test_openapi_upload_paste_configure_edit_and_execute`：真实 Windows WebView 上传 JSON、补地址、保存、编辑、真实测试、粘贴 YAML 再次导入及 1440／390px 布局。截图和日志在 `.scratch/tools-workflow/`。

最终验证及两路审查见 [审查记录](openapi-basic-import.review.md)。
