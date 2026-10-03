# 导出已提交会话与完整工具记录

Status: ready-for-agent

实施进度：待实施

来源：[统一实施规格](../../../../.scratch/frontend-completion/PRD.md)；[公共要求与依赖总览](index.md)。

**What to build:** 导出点击时已加载的已提交消息，包含完整工具记录和中止正文，范围可核对且原文不会破坏记录结构。

**Why:** 以已经确认的持久事实形成可靠会话记录，导出操作保持用户选择的时间与范围。

**API／边界：**完整消息／工具事实快照、Markdown 序列化、Clipboard 原文来源与 UTF-8 Blob 下载；无需新增导出 HTTP。

**Blocked by:** [完整呈现工具调用、结果与附加数据](08-complete-tool-records.md)；[执行失败后保存已生成的中止正文](11-failure-partial-message.md)。

## 验收条件

- [ ] 点击捕获当前会话已加载已提交消息快照，后到不混入，不 GET 更多；无消息提示，预览／草稿／审批选择及审批等运行事件不导出。
- [ ] 按 seq 导出用户、Agent、tool_calls 的完整字段／参数、结果真实 status、非 null artifact、中止正文／generation_status，ToolMessage 只一次，UI 合并不重复。
- [ ] 文件头标标题／身份、时间、消息数、Run 和 seq 范围，说明空洞和不是服务端全部历史，标题与元数据转义，安全文件名缺省会话。
- [ ] 正常完整 Agent Markdown 保持可读，中止或未闭合围栏／HTML 等用原文 markdown 围栏，用户／工具 text、结构化／块数组完整 JSON，动态围栏长度不被原文提前结束。
- [ ] 保留首尾空白、未知字段、artifact 空值和正文外原因，不补写答案；本地资源仅原引用，无图片／文件打包或额外读取。
- [ ] 公开记录夹具与实际 Tauri 下载验证快照时点、长围栏、取消／失败、空记录、保存取消／失败不改事实，所得 UTF-8 文件可完整核对。

## Comments

尚无实施或验收记录。
