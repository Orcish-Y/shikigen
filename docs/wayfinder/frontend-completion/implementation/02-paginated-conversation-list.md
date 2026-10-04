# 自动分页浏览带状态的会话列表

Status: done

实施进度：已验收

来源：[统一实施规格](../../../../.scratch/frontend-completion/PRD.md)；[公共要求与依赖总览](index.md)。

**What to build:** 按真实更新时间浏览带中文状态的会话，滚动到底自动读取更早的 20 条，并能区分加载、无匹配、失败和没有更多。

**Why:** 为会话浏览建立真实分页与状态摘要，避免列表更新或过滤改变当前对话。

**API／边界：**GET /api/threads 的 data／next_cursor；必填正整数 limit（前端首版传 20）与可选 cursor；共享会话数据层、列表滚动与本地过滤。

**Blocked by:** [打开会话并核实运行状态](01-open-conversation-run.md)。

## 验收条件

- [x] 响应保留既有会话字段，增加同一当前／最近发起 Run 的 run_id／run_status；尚无 Run 时两者均 null，旧 Run 晚结算不改变最近发起身份。
- [x] 前端每页传 limit=20，后端与 store 按请求条数分页；updated_at DESC／id DESC；游标不透明并冻结签发时的时间／ID 边界，无效 422；状态和影响排序的更新时间同次提交，查询和 delta 不更新时间。
- [x] 到底／聚焦列表的 End 或 PageDown 自动读下一页，无正常加载更多按钮；原始 data 少于 20 或 next_cursor=null 停止并显示没有更多，不使用过滤数或去重新增数判断。
- [x] 按 ID 更新、插入和去重，保持真实排序、当前选择和草稿；独立保有分页进度，第一页请求不删除更早页，缺项不解释为删除。
- [x] 无过滤且不足可视区可自动填充；过滤只匹配已加载显示标题，明确标范围，过滤后明确向下滚动仍可触发一页，不因键入过滤读完全部历史。
- [x] 首次无事实使用等高 skeleton，刷新保留列表，更多页底部加载／原位失败重试；失败哨兵不无限请求，Retry-After 及无效游标显式重载可用。
- [x] 公开接口与页面覆盖 0／20／21／40／41 条、相同时间、重复 ID、游标边界变化、过滤少匹配和失败，主聊天阅读与观察不受分页影响。

## Comments

### 2026-10-04：实现与验收进展

- 后端：`ThreadStore` 提供固定 20 条的游标分页和同一 Run 的身份／状态摘要；游标冻结时间／ID，纯读接口统一 `no-store`、422、503／`Retry-After: 1` 和 500。
- 客户端：第一页合并与更早页游标独立，按 ID 去重并拒绝更新时间回退；当前 metadata 保有状态优先级。分页和重载列表保留会话选择、草稿及聊天观察。
- 页面：沿用已有侧栏样式，增加中文状态、范围明确的本地过滤、自动滚动／键盘分页、占位、局部错误和“没有更多”；列表焦点已补入现有靛蓝 `focus-visible` 规则。
- 最终测试使用 `gpt-6-luna`、`max`，分别验证后端、客户端与真实 Tauri。前端 29 项通过；后端分页专项 8 项通过；类型检查和包含焦点／占位间距修复的[最终生产构建](../../../../.scratch/frontend-completion/ticket-02-final-build.log)通过。
- Python 初次全量运行 285 项：282 项通过，1 个测试方法的两个子场景失败、1 项错误、1 项环境跳过。已修正旧返回格式断言和子进程日志编码；相关两文件 14 项定向回归全部通过。原始日志保留在 [.scratch 验收日志](../../../../.scratch/frontend-completion/ticket-02-python-tests.log)。
- 修复后再次完整回归：[最终 Python 日志](../../../../.scratch/frontend-completion/ticket-02-python-final.log)记录 285 项，284 通过、1 项环境跳过、无失败，耗时 346.431 秒。该回归由轻量测试子 agent 启动，主 agent 在子 agent 终止后读取并核实结果。
- [Standards 审查](../../../../.scratch/frontend-completion/ticket-02-backend-report.md)未发现阻塞项；[Spec 审查](../../../../.scratch/frontend-completion/ticket-02-spec-report.md)未发现已确认的实现偏差，保留真实键盘与过滤界面的验收缺口。
- 真实 Tauri 已读取与 HTTP 一致的首 20 条；实际视口为 1440×900 CSS px，DPR 为 2，行与占位主体实测均为 63px。原生键盘测试未捕获到目标按键事件，未作为通过结果，也未据此认定产品缺陷。证据见[原生验收目录](../../../../.scratch/frontend-completion/ticket-02-native/)。
- **上轮未完成：**真实 End／PageDown／滚动分页、页面总数 0／20／21／40／41 的停止边界、过滤少匹配、页面失败／Retry-After／422 重载、聊天阅读和观察不受影响，以及最新焦点与占位间距的实机复核。原有 4 项 Tauri 回归上轮尚未执行。
- **上轮中断原因：**测试子 agent 返回 `Your workspace is out of credits. Add credits to continue.`，无法继续启动轻量模型测试。本轮已恢复轻量模型验证；当前剩余项见下节，额度中断不再是当前阻塞原因。

### 2026-10-04：续验收与桌面 CORS 补修

- 最终验证仍由 `gpt-6-luna`（`max`）执行，主 agent 核对原始日志、结构化结果和截图。测试使用独立 Tauri 标识、临时 SQLite、确定性 Agent 与隔离端口，未调用真实模型服务；证据见[续验收报告](../../../../.scratch/frontend-completion/ticket-02-native-resume/report.md)。
- 发现并修复桌面跨端口请求无法读取 `Retry-After` 的问题：在 `app/desktop.py` 的 CORS 中暴露该响应头，并新增公开桌面 HTTP 回归。两个既有允许来源均通过，外部来源仍不获允许来源头。补修的 [Standards](../../../../.scratch/frontend-completion/ticket-02-cors-standards-review.md) 与 [Spec](../../../../.scratch/frontend-completion/ticket-02-cors-spec-review.md) 审查均无代码 finding。
- [本轮完整 Python 回归](../../../../.scratch/frontend-completion/ticket-02-python-cors-final.log)：286 项，285 通过、1 项因 Windows 符号链接权限跳过、无失败。桌面专项 12／12、生命周期 3／3、新 CORS 回归 1／1、补修文件 Ruff 和生产 Python 类型检查均通过，详见 [CORS 回归报告](../../../../.scratch/frontend-completion/ticket-02-cors-report.md)。前端未因本次 CORS 补修改变，沿用已通过的 29 项测试、类型检查及生产构建。
- 4 项既有 Tauri 客户端业务路径补齐：首次批次 3 通过、1 项在退出阶段的托盘坐标断言失败；保持原业务断言与退出 helper 的单项重测通过。0／20／21／40／41 五种数量均验证 HTTP 全页边界与 WebView 首屏；0 条首次探针误把未就绪页面当空列表，补充就绪条件后重测通过。原始失败日志均保留。
- 41 条真实列表的完整 20／20／1 分页通过：键入少匹配／无匹配过滤不触发额外 GET，显式滚轮和 End 分别只加载一页，最终显示“没有更多”；保持会话选择、草稿和已有聊天请求。End 事件在该场景的 WebView 审计中为 `isTrusted=true`。该证据来自 CDP 输入，不代表物理 Windows 键盘通过。
- [真实 503 场景](../../../../.scratch/frontend-completion/ticket-02-native-resume/real-503-cors-visible-retry/test_real_503_retry_after_is_cors_readable/result.json)：实际后端返回 `Retry-After: 1`，同一 WebView 的跨端口 fetch 能读取该值；倒计时前保留 20 行、禁用重试，观察窗内没有自动重试。错误与按钮滚动可达，解锁后的可信 CDP 点击只重试同一游标一次，恢复到 21 行并清除错误。
- [真实 422 场景](../../../../.scratch/frontend-completion/ticket-02-native-resume/invalid-cursor-visible-error/test_real_422_requires_explicit_reload_and_preserves_rows/result.json)：无效游标保留 20 行并停止自动请求；错误区的“重新加载会话列表”按钮可见，可信 CDP 点击后发出不带游标的 GET，重载期间保留列表、选择、草稿及聊天请求，成功后清除错误。
- [长历史与活动 SSE 专项](../../../../.scratch/frontend-completion/ticket-02-native-resume/active-sse-pagination-verified/test_active_sse_and_midscroll_chat_survive_sidebar_pagination/result.json)最终 1／1 通过：80 段历史正文停在中段，稳定采样的 scrollTop 为 3600、可见锚点为第 032 段、相对顶部为 6px；列表从 20 条读取到 40 条时只新增一个游标 GET，聊天位置、锚点、选择和草稿不变，历史／流请求无分页引起的变更。WebView 中同一 POST 响应在分页期间未 abort／EOF，放行后继续交付包含完成正文的 5 个原始 chunk 并自然 EOF，没有重开 POST。
- 上述活动连接专项的前置夹具缺少审计 helper、滚轮未稳定时取基线，以及把自然结束后的清理误算作分页影响，分别有原始失败日志；最终测试保留分页期间不 abort／不重读的断言，并新增原响应字节与 EOF 审计。发送开始时已完成的历史 GET controller 被清理，POST 自然结束后客户端按既有契约清理旧 controller、补读历史及第一页；这些时序均与分页无关，不能声称所有历史请求的 signal 全程未 abort。5173 的既有静态服务只读复用，index／JS 与已通过构建的 frontend/dist 逐字节一致；测试未终止归属未确认的该服务。
- 当前实测 CSS 内容区为 1440×900、DPR 2；行与 skeleton 主体均 63px、底部间距均 4px，焦点 outline 为现有靛蓝 2px、offset 3px。截图为 WebView 内容，不包含原生窗口边框。
- [PageDown 最终专项](../../../../.scratch/frontend-completion/ticket-02-native-resume/page-down-pointer-retry/test_one_page_down_after_trusted_blank_nav_click/result.json)及[执行日志](../../../../.scratch/frontend-completion/ticket-02-native-resume/page-down-pointer-retry.log)记录 1／1 通过、9.103 秒。先可信点击列表空白，让 WebView 获得实际指针激活；PageDown 的 `isTrusted=true`、目标与焦点均为会话列表 NAV、`defaultPrevented=true`，在无匹配过滤下只新增一个带游标 GET，清除过滤后为 40 条，当前选择与聊天请求保持不变。
- 此前纯脚本 focus 的 `keyDown`／`rawKeyDown` 没有送达事件，不能计为通过；可信点击后首轮已触发请求，但夹具把过滤隐藏的选中行误判为未选择，修正为核对聊天标题并在清除过滤后核实同一行，保持原可信事件与一次请求断言后重测通过。原始失败日志保留。测试子 agent 在成功产物写出后因额度中断，主 agent 在用户要求继续后读取并核实上述完整结果，未重复执行已通过测试。
- **后续联合验收边界：**上述按键与指针为真实 Tauri WebView 中的可信 CDP 输入，不是物理 Windows 键盘／鼠标验收；物理 End／PageDown 注入此前未获得目标事件，不据此判定产品缺陷。原生焦点、IME、窗口边框及多尺寸证据归入既有[第 23 票](23-native-workflow-acceptance.md)。API 的五种数量全页边界与 WebView 首屏已验证，不能称五种数量都走完了实机末页。
- 主 agent 已核对接口、客户端、页面、原始 SSE 字节、日志及截图，7 条验收条件完成，本票标记 `done`／已验收；本轮未启动第 3 票。

### 2026-10-04：页长由前端传入

- 按用户追加要求，将“仅 cursor、store 固定 20 条”调整为必填正整数 limit 与可选 cursor。HTTP、ThreadService、ChatStore、ThreadStore 逐层传递；前端首版仍明确传 20，并用同一配置校验页长与判断末页。
- store 使用 limit+1 预读、limit 切片及额外记录判断游标；跨页可改变 limit。补修极大正整数引发的 SQLite 绑定溢出，保留前端指定业务条数。
- 最终验证由 `gpt-6-luna / max` 执行：[补修前完整回归](../../../../.scratch/thread-page-limit/backend-full-suite.log)为 289 方法，288 通过、1 Windows 符号链接权限跳过；SQLite 补修后分页 12、查询 4、Server 16 共 32 个专项通过，未重复整套。前端 30/30、类型检查、构建与五条读取路径参数探针通过；主 agent 已核对原始日志与退出码。
- 13 个指定文件 Ruff 与生产类型检查通过，最终补修两文件再检查通过。原生分页验收脚本的 11 条既有 lint 诊断保留，不计全路径 lint 通过。Standards 无新增违规或 smell；Spec 原发现的整数溢出已修复并补验。详情见[本次完成记录](../../../../.scratch/thread-page-limit/report.md)。
- 本票保持 done／已验收；本次没有新增实机视觉或物理输入证据，第 3 票仍未启动。
