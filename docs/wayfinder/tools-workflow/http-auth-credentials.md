# HTTP 认证与后续凭据设计

2026-10-15 用户决定保留 HTTP 认证，先删除通用 credential 功能，后面统一设计。当前实现使用直接密钥字段；本文替代此前凭据抽象、特殊编辑动作和遮盖机制的实现记录。

## 当前认证配置

HTTP 定义保留 `auth` 数组，每个绑定有稳定 `id`、`kind`、`location`、`name` 和字符串 `value`：

```json
{
  "auth": [{
    "id": "service_token",
    "kind": "bearer",
    "location": "headers",
    "name": "Authorization",
    "value": "your_token_here"
  }]
}
```

Bearer 使用 Authorization 请求头；API Key 支持 headers 或 query。空数组表示无认证，多个绑定全部注入。固定请求头、URL 查询参数、业务参数映射和其他绑定占用同一目标时拒绝保存／草稿测试；请求头名忽略大小写，查询参数名按实际大小写比较。

Bearer 密钥允许直接填写 token 或包含 `Bearer ` 前缀的完整值；执行时仅在缺少该前缀时补上，前缀判断忽略大小写，已有值保持原样。API Key 按原值发送。

`value` 直接保存到项目配置，按字面读取，不展开环境引用。管理列表／详情返回实际值，密码框重新读取后直接回填；填写新值替换，清空并保存写入空字符串。省略整个 `auth` 字段的更新保留原认证，提交 `auth: []` 移除认证。任一绑定没有密钥时执行返回 `authentication_missing`，不发送匿名请求；明确选择无认证后才匿名执行。

密钥不进入业务 input_schema 或工具调用参数；工具草稿和密钥不写浏览器本地存储。当前草稿测试使用本次填写值，保存前不影响消费者取得的已保存配置。工具页继续参照 [demo 与布局规则](../../../frontend/design.md#工具页面原型)，认证仍位于配置卡片的整行区域。

## 已移除并留待统一设计

已删除后端 `Credential`／`CredentialEdit`、编辑合并函数、已知密钥集合、通用结果／错误／日志遮盖、遮盖内容还原、特殊名称 schema，以及前端 `CredentialInput` 和对应读取标志。当前请求不支持 `credential`、`is_set` 或 `clear`；留空不再表示保留密钥。测试结果和日志按原始执行内容处理。

后续涉及 MCP 连接或 OpenAPI 认证时，需要先统一设计凭据的存储、管理读取、保留／替换／清空语义及遮盖范围；不能假设旧模块仍存在，也不要在后续 ticket 中直接恢复旧抽象。HTTP 认证数组、稳定绑定 ID、组合注入和目标冲突校验仍可复用。

11 号票的 OpenAPI 认证导入沿用现有直接值契约，仅解析来源方案并生成 HTTP 绑定；没有新增凭据管理或隐藏协议。具体范围见[OpenAPI 兼容与认证](openapi-compatibility-auth.md)。统一设计的前置要求继续适用于将来新增凭据管理或遮盖机制。

## 保存结果

13 号票补齐配置／代码版本与批次冲突。2026-10-23 用户后续决定：旧代码清理失败只记后端日志，在后续配置提交或启动时重试，不返回清理 `warnings`；创建返回 201 和 ID，更新／删除成功返回空 204。详见[保存与调用生效记录](config-conflicts-call-snapshot.md)。本节后文描述既有响应丢失与重读规则，继续有效。

本地保存不使用额外确认请求头、确认接口或内存缓存。创建返回工具 ID，更新／删除返回空 204；创建／更新成功后页面读取详情。

保存明确被拒绝时保留草稿，允许修正后再保存。收到保存成功响应、但详情读取失败时明确提示“工具已保存，详情读取失败”，只重读详情，不重复提交。

未收到保存响应时显示“保存结果不确定”，保留草稿并锁定再次保存和测试，不自动重试或推断成功／失败。用户可明确选择“放弃草稿并重读工具库”，成功重读后恢复浏览，失败仍保留草稿。重读不证明此前写入成功。保存并离开遇到该情况时，明确放弃并成功重读后才继续原离开操作；完整冲突处理由 ticket 13 接入。

## 验证入口

公开 API 与真实本地 HTTP 服务使用 `tests/test_tool_library_api.py`，覆盖 Bearer、header/query API Key、组合认证、直接读取／替换／清空、草稿与已保存配置分离、缺失和冲突。页面测试使用 `frontend/tests/tool-management-dom.test.mjs`，原生验收使用 `frontend/src-tauri/tests/tool_library_acceptance.py`。

本轮验证日志位于 `.scratch/tools-workflow/verification/ticket04/direct-auth-api.log`、`direct-auth-frontend.log`、`direct-auth-build.log` 和 `direct-auth-native.log`。此前凭据隐藏实现的验收记录不代表当前简化版本的功能承诺。

本轮工具 API 30 项、前端客户端与工具页面 32 项、真实 Tauri 工具页 6 项全部通过；TypeScript／Vite 构建、相关 Python 模块 ty、Ruff 和 diff 检查通过，未重跑前后端全量。已检查原生认证页面的 1440px／390px 截图，字段和密码框可见，无页面横向溢出。截图位于 `.scratch/tools-workflow/verification/native/test_http_auth_password_reads_replaces_and_clears_direct_value/`。
