# OpenAPI 引用、认证与兼容诊断

11 号票扩展已有 HTTP 导入流程，继续遵循[工具页原型规则](../../../frontend/design.md#工具页面原型)和[工具模块布局](tool-module-layout.md)。生成普通 HTTP 工具，执行仍使用现有适配器。

## 请求转换

解析当前接口实际使用的内部 `#/...` schema、parameter、requestBody 引用，支持链式引用及 JSON Pointer 转义。通过当前递归路径检测循环，重复使用同一结构、普通嵌套对象和数组不会被误判。外部引用不访问网络，缺失、循环和不支持的位置明确诊断。3.1 引用旁的说明注解可保留；需要合并约束的引用同级字段先提示不支持，不覆盖目标约束。

保留对象、数组、原名、必填、枚举、数值范围／倍数、字符串模式／长度、数组边界／唯一性、普通附加属性约束。3.0 nullable 和布尔 exclusive 范围转换到工具已有方言；3.1 单一类型加 null，以及一个普通结构与 null 的 anyOf／oneOf 转换为等价类型，包括两分支都使用内部引用。枚举分支与 null 合并时保留 null。显式声明标准 OAS 3.1 或 Draft2020 方言可导入；分支重叠的 oneOf、通用组合、自定义 dialect 和其他未支持约束会阻止该接口保存。`format` 保留为注解，不额外启用格式校验。

path/header 接受普通标量，query 接受 form 标量或非空标量元素数组，沿用原始 explode。路径占位符与必填映射必须相符。请求体从多媒体内容中选取 application/json，保留整个 body 与其字段的必填性；文件、表单、cookie、对象 query、特殊序列化、参数 content、特殊保留字符要求均明确未支持。

转换不修改文档。来源保存当前 operation、路径级配置、服务器、实际访问的引用片段和认证来源；未使用的复杂 components 不参与转换。未支持的接口也能查看其来源。

## 认证方案

operation 的 security 优先，缺省继承文档级；来源明确允许的 `[]`、`[{}]` 或空备选要求表示无认证。每个非空要求对象是一组必须全部满足的绑定，security 数组中的对象互为备选。预览默认选择第一个受支持方案，并允许切换；未支持方案显示原因且不能选择，不自动添加匿名方案。

支持 Bearer、header/query API Key。生成确定的绑定 ID，所有密钥保留在 `auth[].value`，不放进 input_schema。目标冲突按 HTTP 契约检查，包括头名大小写、组合绑定、业务映射与 Content-Type。缺值属于需要补配置；同一方案有任一未支持要求或冲突，则整个方案不可用。

沿用用户已确认的[直接认证值契约](http-auth-credentials.md)：密码框直接编辑、保存和回填实际值，凭据管理与隐藏机制留待统一设计。导入保存要求所选方案全部认证值齐备，不能删绑定后匿名导入。

## API 和页面

预览 API 补充 `security_options: [{id, label, auth, errors}]` 和默认 `security_option`；导入选择可提交 `security_option`，省略时使用预览默认方案。后端从原文档重新构造方案，检查方案受支持、绑定满足全部目标及值已补齐，将 `selected_security` 写入来源记录。不会信任客户端删除错误或删去认证要求。

页面保留概览、7:5 双栏和窄屏堆叠。每项显示可保存／需要补配置／未支持；来源方案位于预览卡，密钥仍在 HTTP 配置卡内。切换接口保留配置；切换来源方案重新建立对应绑定。诊断带方法、路径、字段／引用位置、原因及修正或取消选择的动作。

所有选中项就绪才整批保存；后端验证全部定义，一次提交。取消缺配置项后可保存其余正常接口。单一受支持 JSON 成功结构预填 output_schema；输出引用也可解析，复杂、多结构和不可用输出留空解释，不阻止有效请求。实际响应完整返回。

## 验证

公开 API 与真实本地 HTTP 服务见 `tests/test_openapi_import_api.py`，页面交互见 `frontend/tests/openapi-import-dom.test.mjs`。原生验收扩展 `test_openapi_upload_paste_configure_edit_and_execute`，覆盖内部引用、方案诊断、组合密钥补齐、来源查看、真实带认证请求及 1440／390px 布局。

最终检查与审查结果见[审查记录](openapi-compatibility-auth.review.md)。范围依据项目[首版决议](tickets/005-openapi-import-scope.resolution.md)，参考 [OpenAPI 3.0.4](https://spec.openapis.org/oas/v3.0.4.html) 和 [3.1.2](https://spec.openapis.org/oas/v3.1.2.html)；这是本项目确认的子集。
