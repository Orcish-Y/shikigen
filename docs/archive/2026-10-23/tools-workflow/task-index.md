# 工具模块开发任务

> 历史规格：保留发布时的状态与待实施描述，用于追溯需求和拆票依据。当前开发从[工具库指南](../../../wayfinder/tools-workflow/README.md)进入；本文不是当前待办清单。

来源：[开发规格](PRD.md)。用户已确认 14 项拆分及依赖，按 `to-tickets` 技能发布到[项目本地 tracker](../../../agents/issue-tracker.md)。每项任务各有独立文件，状态为 ready-for-agent；该状态表示规格可执行，不表示功能已实现。

每张票贯通对应定义、公开 API、页面和行为验证。后端以公开 HTTP API 为主要测试边界，使用临时配置、真实 Python 子进程、本地 HTTP/MCP 服务；前端沿用公开状态测试，并完成该票页面交互验收。具体组件选型、schema、执行和保存契约以开发规格为准。

组件基础已在后续工作中接入：shadcn 基础控件、AI Elements Reasoning、rjsf 6.11.0 依赖和 Testing Library/jsdom 设施见[接入记录](../../../../frontend/component-libraries.md)。01 复用这些基础并接入真实业务 Form/Tool，02 验证主题、方言/format 与输入保持，12 验证真实状态和所有 JSON 结果展示；14 项任务及依赖保持不变。后续工作流建议采用 React Flow 图交互基础加 AI Elements 工作流 UI，图编辑和字段映射仍由后续专项实施。

## 任务与依赖

| 任务 | 阻塞项 | 对应用户故事 |
| --- | --- | --- |
| [01：创建并测试第一个 HTTP 工具](../../../wayfinder/tools-workflow/implementation/01-first-http-tool.md) | 无 | 1、2、5、6、7、9、18、48、52、54、55、64 |
| [02：HTTP 参数映射与动态表单](../../../wayfinder/tools-workflow/implementation/02-http-parameters-schema-forms.md) | 01 | 15、16、17、36、37、61、66 |
| [03：工具编辑、启用、删除与草稿测试](../../../wayfinder/tools-workflow/implementation/03-tool-edit-drafts.md) | 01 | 3、4、8、10、11、12、13、14、46、47、51、59 |
| [04：HTTP 认证（凭据管理待统一设计）](../../../wayfinder/tools-workflow/implementation/04-http-auth-credentials.md) | 02 | 44、45 |
| [05：创建并测试带注解的 Python 工具](../../../wayfinder/tools-workflow/implementation/05-python-tool-execution.md) | 02 | 19、20、24、25、26、27 |
| [06：Python 类型补齐与源码变更同步](../../../wayfinder/tools-workflow/implementation/06-python-schema-sync.md) | 03、05 | 21、22、23 |
| [07：接入 stdio MCP 并调用选中工具](../../../wayfinder/tools-workflow/implementation/07-mcp-stdio-tools.md) | 04 | 28、29、30、31、32、53、65 |
| [08：接入 Streamable HTTP MCP](../../../wayfinder/tools-workflow/implementation/08-mcp-streamable-http.md) | 07 | 28、30、53 |
| [09：MCP 重新发现与连接生命周期](../../../wayfinder/tools-workflow/implementation/09-mcp-discovery-lifecycle.md) | 03、07 | 33、34、35 |
| [10：OpenAPI 基础导入与工具编辑](../../../wayfinder/tools-workflow/implementation/10-openapi-basic-import.md) | 02、03 | 38、39、40、43 |
| [11：OpenAPI 引用、认证与兼容诊断](../../../wayfinder/tools-workflow/implementation/11-openapi-compatibility-auth.md) | 04、10 | 41、42 |
| [12：测试取消、超时与运行中交互](../../../wayfinder/tools-workflow/implementation/12-test-cancellation-lifecycle.md) | 03、05、07 | 48、49、50 |
| [13：保存结果、外部修改与调用生效规则](../../../wayfinder/tools-workflow/implementation/13-config-conflicts-call-snapshot.md) | 03、05、07 | 56、57、58、63 |
| [14：稳定 ID 复用与非 LLM 参数传递](../../../wayfinder/tools-workflow/implementation/14-stable-id-consumer-reuse.md) | 13 | 60、61、62、63 |

故事号对应开发规格中的 66 条用户故事；跨票复用的行为可出现在多个验收场景中。验收标准在每张独立票中，不以本索引代替任务正文。

## 开始与推进

涉及工具页的 ticket，开发与验收先读取并遵循[工具页面原型与参照规则](../../../../frontend/design.md#工具页面原型)；每张开发票已添加同一依据入口。

发布时尚无已完成开发票，当前可开始 [01：创建并测试第一个 HTTP 工具](../../../wayfinder/tools-workflow/implementation/01-first-http-tool.md)。以后读取票据实际状态，只有全部阻塞项已完成的任务才进入可执行集合；编号顺序不要求把所有分支串行完成。

每票完成自身验收与必要检查后，再推进解锁任务。中间阶段只支持已完成票的能力，后续类型和高级边界按各自票扩展；不能把阶段子集当成最终首版已完成，也不以临时不支持代替后续票的实现。

本索引最初随任务发布创建，后续根据已完成组件接入更新了开发规格及 01、02、12 的验收要求。当前工具模块应用代码、部署和产品验收尚未执行；已有组件专项的验证记录不等同于工具模块验收。
