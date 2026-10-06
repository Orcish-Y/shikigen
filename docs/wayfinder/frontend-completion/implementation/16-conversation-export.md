# 导出已提交会话与完整工具记录

Status: done

实施进度：已验收

来源：[统一实施规格](../../../../.scratch/frontend-completion/PRD.md)；[公共要求与依赖总览](index.md)。

**What to build:** 导出点击时已加载的已提交消息，包含完整工具记录和中止正文，范围可核对且原文不会破坏记录结构。

**Why:** 以已经确认的持久事实形成可靠会话记录，导出操作保持用户选择的时间与范围。

**API／边界：**完整消息／工具事实快照、Markdown 序列化、Clipboard 原文来源与 UTF-8 Blob 下载；无需新增导出 HTTP。

**Blocked by:** [完整呈现工具调用、结果与附加数据](08-complete-tool-records.md)；[执行失败后保存已生成的中止正文](11-failure-partial-message.md)。

## 验收条件

- [x] 点击捕获当前会话已加载已提交消息快照，后到不混入，不 GET 更多；无消息提示，预览／草稿／审批选择及审批等运行事件不导出。
- [x] 按 seq 导出用户、Agent、tool_calls 的完整字段／参数、结果真实 status、非 null artifact、中止正文／generation_status，ToolMessage 只一次，UI 合并不重复。
- [x] 文件头标标题／身份、时间、消息数、Run 和 seq 范围，说明空洞和不是服务端全部历史，标题与元数据转义，安全文件名缺省会话。
- [x] 正常完整 Agent Markdown 保持可读，中止或未闭合围栏／HTML 等用原文 markdown 围栏，用户／工具 text、结构化／块数组完整 JSON，动态围栏长度不被原文提前结束。
- [x] 保留首尾空白、未知字段、artifact 空值和正文外原因，不补写答案；本地资源仅原引用，无图片／文件打包或额外读取。
- [x] 公开记录夹具与实际 Tauri 下载验证快照时点、长围栏、取消／失败、空记录、保存取消／失败不改事实，所得 UTF-8 文件可完整核对。

## Comments

2026-10-06：实现事实快照、完整 Markdown 序列化及工具栏 UTF-8 Blob 下载。以编辑前文件副本固定审查点，不执行 Git 命令。显式 `gpt-6-luna / max` 执行完整 Node 基线188通过；围栏／字段修正后的最终导出专项7通过，TypeScript／构建及最新两Python文件Ruff通过。六个正式Tauri导出场景＋两个既有回归，共八个唯一用例分批各有通过证据，不声称一次8／8全绿。实际UTF-8文件、点击后新消息排除、完整HTTP记录、中止正文与真实原因、空记录、同步失败及真实WebView同GUID下载取消均有证据；主agent已核对原始日志、字节、JSON与截图，六条验收对应见[实施与验证报告](../../../../.scratch/frontend-completion/ticket-16/report.md)。

Standards／Spec无剩余硬问题；lifecycle文案与Run.error分字段保留。早期CDP连接错误与误改夹具标记导致的失败均保留。默认SaveAs窗口探针两次失败，代码及日志不删除、不改算通过；规格未要求特定窗口形态，实际下载取消已验证。默认保存UI／目录和物理用户操作仍未验证，归第23票联合实机检查；CDP指定隔离目录不代表默认UI通过。无后端／Rust产品、HTTP或依赖变更，未重复相关全套回归。当前Vite主chunk595.78kB提示保留。
