# 完整呈现工具调用、结果与附加数据

Status: ready-for-agent

实施进度：待实施

来源：[统一实施规格](../../../../.scratch/frontend-completion/PRD.md)；[公共要求与依赖总览](index.md)。

**What to build:** 在调用下查看对应参数和真实结果，失败首次展开，完整读取与复制 artifact 和未配对结果。

**Why:** 让用户核对每项真实工具行为，同时保留长对话的阅读节奏。

**API／边界：**AI tool_calls、Tool tool_call_id／status／artifact；完整事实与共用 JSON／只读查看。

**Blocked by:** [安全 Markdown、网页链接与完整内容查看](07-markdown-content-viewer.md)。

## 验收条件

- [ ] 同会话、同 Run、tool_call_id 唯一关联，按 tool_calls 顺序展示，保留原调用与结果的各自 seq；无唯一对应时独立结果，不猜工具、参数或到达匹配。
- [ ] 等待结果、已返回、工具失败依据实际 ToolMessage／status，正文 Error 字样不改变状态；Run 已结束且无结果仍保留等待并说明运行结束，不造取消／失败 ToolMessage。
- [ ] 空正文说明已返回且为空，额外字段、不同结果名称和未知结构可完整核对；不伪装为第二条 Agent 回答。
- [ ] 默认折叠，失败首次仅打开卡片及结果，参数／artifact 仍折叠；稳定调用身份记应用内手动收起，重复回放不重开，重启重新应用默认。
- [ ] 非 null artifact 包括空字符串、0、false、空数组／对象均完整只读；省略／null 不造空区，不猜文件／媒体，不增加另一套审批。
- [ ] 复用完整查看与复制，不撑宽页面；公开消息夹具覆盖多个同名调用、乱序结果、无法匹配、空值及重复失败，并在工作台演示。

## Comments

尚无实施或验收记录。
