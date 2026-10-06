# 首版 Tauri 聊天工作台实施票据

Status: ready-for-agent

补齐首版真实聊天、运行恢复、审批／取消、中止正文保存、完整内容与资源、详情和导航；来源：[统一实施规格](../../../../.scratch/frontend-completion/PRD.md)。

发布日期：2026-10-04。用户已确认 23 张票据的粒度、直接阻塞依赖及拆分安排，答复“按方案定稿并发布（推荐）”。共 156 条验收条件；第 1–22 票已实现并完成各票核心验收，其余票据待实施。完整仓库回归的未解决问题另行记录，不能将票据完成等同于所有仓库测试通过。

文件组织：2026-10-04 按用户提出的目录与粒度要求，每张实施票据独立保存于本目录。本索引汇总公共要求与直接依赖；原有 [Wayfinder 地图](../map.md)及 tickets/ 记录规划决策。

工作 frontier：阻塞票全部完成的票即可开始，每次推进一票；以下按依赖顺序编排，独立分支可自行安排。2026-10-07 第1–22票已完成。下一票为 **第23票“首版 Tauri 全流程与原稿实机验收”**，本轮未开始其实施。

第22票完成：**第22票“本地命令面板与受限全局快捷键”**。只搜索操作与已加载显示标题，共享新建／切换／导航／详情及pending，普通输入可用的平台快捷键、IME／repeat／单前景保护、Tab／Esc与焦点返回；独立过滤与原文草稿保留，窄屏不写桌面偏好。显式 `gpt-6-luna / max` 命名修正前唯一完整Node **268通过**，修正后受影响专项 **13通过**，类型与最后CSS改动后构建、三文件Ruff通过；不累计重叠单测或声称最终重复全套。五个本票原生唯一场景分批各有最终通过证据，另两项既有导航／原文IME重启回归通过；四档实测dialog480／480／480／358px，DPR1.5／DPI144与Win32记录保留。Standards硬项0／低风险观察1，Spec六AC符合且无未决遗漏／错误实现／范围蔓延；主agent核对六条验收后关闭。双记录器、390px宽度和取证／格式失败及完整命令见[第22票报告](../../../../.scratch/frontend-completion/ticket-22/report.md)。物理Windows输入／OS候选窗、原生标题栏及全流程联合验收归第23票，macOS Cmd仅单测；Vite主chunk642.05kB告警保留。无后端／Rust产品、API、依赖或配置变更，本轮未执行任何Git命令。

第21票完成：**第21票“原稿风格的响应式导航与桌面偏好”**。四档CSS布局、主动桌面偏好跨重启、手机默认会话列表与同面板导航、单前景及焦点恢复，保留过滤／分页／列表位置／原文草稿／聊天锚点；恢复原稿品牌层级、字体／间距与主按钮hover，输入48→180及宽度换行、托盘／提示占位和短导航头尾可达。显式 `gpt-6-luna / max` 最终完整Node **255通过，0失败／取消／跳过**，TypeScript／构建及四Python文件Ruff通过；真实Tauri final-3单批 **4／4通过，0失败／错误／跳过**，四档1440×900／1280×800／1024×768／390×844实测DPR2／DPI192及Win32窗口记录、截图对照。Standards硬违规0／明确异味0，Spec七AC符合且无遗漏／错误实现／范围蔓延；主agent核对七条验收后关闭本票。旧CDP连接、动画取样和seed夹具失败保留，完整命令、模型、日志及边界见[第21票报告](../../../../.scratch/frontend-completion/ticket-21/report.md)。K／N／B的输入法／repeat／模态协议由第22票承担，物理输入／OS剪贴板／原生标题栏外观和全流程联合验收归第23票；Vite主chunk635.70kB提示保留。无后端／Rust产品、API、依赖或配置变更，本轮未执行任何Git命令。

第20票完成：**第20票“会话标题、日期时间与空态引导”**。首条已提交明确用户文本派生标题、跨重启缓存和完整历史核对、服务端正式标题优先、共用列表／工具栏／过滤与完整标题／时间抽屉；本地日历及相对时间、七天日期、未来／未知边界、可见分钟及重新显示刷新不增HTTP；三例原文追加与输入／模态焦点保护。显式 `gpt-6-luna / max` 最新完整Node **246通过，0失败／跳过／取消**，TypeScript／构建及三个Python文件Ruff通过；最新真实Tauri final-5单批 **4／4通过，0失败／错误／跳过**，包含缓存跨原生重启、只标题存储故障不误报持久草稿、正式标题／本地时区及UTC复制、迟到历史、真实隐藏／托盘恢复。Standards硬性违规0／判断性建议0，Spec六AC符合且严重度发现0；主agent核对六条验收后关闭本票。历史夹具失败和受限权限CDP初始化失败保留，权限执行获准后完整复验；命令、模型、计数、截图及边界见[第20票报告](../../../../.scratch/frontend-completion/ticket-20/report.md)。物理输入／OS剪贴板／原生边框和多尺寸联合检查归第23票，Vite主chunk631.72kB提示保留。无后端／Rust产品、依赖或API变更，本轮未执行任何Git命令。

第19票完成：**第19票“有限核实待结算用量”**。共享纯读 GET、首次 EOF／取消免费补读、五秒完成后等待、最多12次后续请求、有限错误恢复／Retry-After、阶段预算与所有者隔离、false终止自动任务、暂停文案与人工继续。显式 `gpt-6-luna / max` 最终六文件 **82通过**（含22新增），后端用量专项 **9通过**，类型／构建／三个Python文件Ruff通过。较早唯一完整Node **224项：223通过／1失败**，修复后原断言在最终专项通过，完整未重跑。原生行为批次 **4／4通过**，取证与稳定握手修正后两项复验 **2／2通过**，四个唯一场景分批各有最终证据，不累计为六项或声称最后单批重跑四项。真实五秒／十二次暂停／手动继续、503三次恢复、同updated_at取消晚量与事件／审批／阅读位置已核对；原始快照与公开fetch注入分开记录。Standards／Spec无硬遗留，主agent核对七条验收后关闭本票。旧CDP失败、权限等待中断和采集别名问题保留，完整过程、命令、模型、截图和覆盖边界见[第19票报告](../../../../.scratch/frontend-completion/ticket-19/report.md)。原生边框／物理输入／多尺寸联合验收归第23票，Vite主chunk622.80kB提示保留。无后端／Rust产品或依赖变更，本轮未执行任何Git命令。

第18票完成：**第18票“查看已提交运行事件与审批历史”**。新增纯读全量events JSON，与SSE共用投影；详情并行独立读、事实seq合并／冲突整批回滚、真实生命周期及审批、完整JSON与同前景查看、一次EOF／取消补读，关闭只停专属读。显式 `gpt-6-luna / max` 完整后端333项 **332通过／1 Windows权限跳过／0失败或错误**、较早完整Node **208通过**；最后诊断／命名／样式改动后后端专项 **5通过**、前端三文件 **40通过**，类型／构建／Ruff通过。原生 **五个唯一用例分批各有通过证据**，历史连接失败与提升权限4通过／1滚动失败保留，修复后完整JSON／复制／阅读位置及最后12px／20px字体断言通过，不声称一次5／5或最终全套全部重跑。Standards／Spec硬遗留0项，主agent核对七条验收后关闭本票。完整命令、版本范围、失败和截图见[第18票报告](../../../../.scratch/frontend-completion/ticket-18/report.md)。Vite主chunk616.93kB提示保留；系统剪贴板／原生边框／物理输入／多尺寸联合验收归第23票。无Rust产品或依赖改动，未重复其全套。本轮未执行任何Git命令。

第17票历史结果保留：**第17票“查看当前运行详情与真实累计用量”**。接入真实Run身份／状态／服务端时间／错误及累计用量、共享纯读快照协调、字段与执行阶段版本、沿用原稿样式的摘要和详情、单前景完整只读视图。显式 `gpt-6-luna / max` 执行完整Node早期195项中 **194通过／1失败**；隐藏恢复状态修复后最新受影响6文件 **72通过**，两项取消竞态与首帧前待确认已覆盖；完整套件未重跑，旧失败保留。最终TypeScript／构建及Python夹具Ruff通过。五个本票原生场景＋两个消息／工具回归，共 **七个唯一用例分批各有最终通过证据**，不声称一次7／7全绿；CDP握手和DPI／读取文案夹具失败保留。Standards／Spec无遗留硬性问题、2项可读性建议保留；主agent核对七条验收后关闭本票。真实HTTP／SQLite／Graph离线模型回调、微秒UTC复制、400 CSS px、零／未知／多模型、同updated_at取消晚量、外部新Run和旧GET失效均有证据。第18票事件与第19票有限轮询尚未实施，物理输入／OS剪贴板／原生窗口边框和多尺寸联合检查仍归第23票。完整记录见[第17票报告](../../../../.scratch/frontend-completion/ticket-17/report.md)。无后端／Rust产品和依赖变更，未重复相关全套回归；Vite主chunk606.40kB提示保留。本轮未执行任何Git命令。

第16票历史结果保留：**第16票“导出已提交会话与完整工具记录”**。点击时捕获完整已提交事实快照，按seq保存完整工具字段、未知字段和中止正文，生成范围明确的UTF-8 Markdown文件，保持当前工具栏样式。显式 `gpt-6-luna / max` 执行完整Node基线 **188通过**；围栏／字段修正后的最终导出专项 **7通过**，TypeScript／构建及最新两Python文件Ruff通过。六个正式Tauri导出场景＋两个既有回归，共 **八个唯一用例分批各有最终通过证据**，不声称一次8／8全绿；实际文件逐字节核对，真实下载GUID取消不改消息／草稿／Run。Standards／Spec无剩余硬问题，主agent核对六条验收后关闭本票。默认SaveAs探针两次失败保留，默认保存UI／目录和物理用户操作未验证，归第23票联合实机检查；不把deny当取消或把未验UI算通过。完整过程、失败批次、命令、文件及截图见[第16票报告](../../../../.scratch/frontend-completion/ticket-16/report.md)。本票无后端／Rust产品或依赖修改，未重复相关全套回归；Vite主chunk595.78kB提示保留。本轮未执行任何Git命令。当时下一票为第17票，未在第16票实施轮次开始。

第 15 票历史结果保留：**第 15 票“每次确认后用系统程序打开工作目录文件”**（宿主自管资源核实、一次性意图、统一确认、目标版本复验与来源／租约作废）。显式 `gpt-6-luna / max` 执行完整Node **179通过**及完整Rust **34通过**作为后续修正前基线；锁修复后Rust专项 **10通过**，最后仅测试变量改名做no-run编译与格式检查，未重跑行为测试。交互修复后Node专项 **21通过**，最后纯命名和只读文案后专项 **15通过**，两批重叠不相加；最终TypeScript、构建、宿主example及两Python文件Ruff通过，资源HTTP **8通过**。当前构建原生先探针 **1通过**，再剩余7专项＋3回归 **10通过**，分批共 **11个唯一用例**有最终通过证据，不声称一次11／11全绿。真实默认程序与无默认关联文件均有系统派发证据；实际后端进程失败亦已验收。五分钟边界使用Rust虚拟时钟，ready→ready租约帧为公开桥模拟，系统接受不承诺文件内容显示。Standards／Spec 无剩余硬问题，1项来源参数封装建议保留；主agent核对六条验收后关闭本票。历史原生9通过／2失败及11项连接失败不改算通过，完整过程、命令、截图与范围见[第15票报告](../../../../.scratch/frontend-completion/ticket-15/report.md)。Vite主chunk591.51kB提示保留。本轮未执行任何Git命令。

第 14 票历史结果保留：固定工作目录资源身份、纯 GET 解析／图片、受控 Blob 预览与详情、局部重试、租约清理及段落阅读锚点。显式 `gpt-6-luna / max` 执行完整后端 **329 项：328 通过、0 失败／错误、1 Windows symlink 权限跳过**；最后等价命名／未使用字段调整后 HTTP8、后端 Ruff／ty 通过，未重复完整后端。App 租约详情逻辑修复后完整前端 **172 通过**；最后纯局部变量改名后 TypeScript、构建和原生定向 **1 通过**。原生首批 **7 项：4 通过、1 失败、2 错误**，夹具修正后图片三项 **3 通过**；租约详情红灯 **1 失败**保留，修复后最终绿灯通过。分批 **8 个唯一原生用例**各有通过证据，不声称一次 8／8 全绿；新租约用例模拟公开 Tauri 桥状态帧，不代表实际 BackendManager 重启。Standards／Spec 无剩余硬问题；主 agent 核对七条验收证据并关闭本票，完整过程、命令、截图与覆盖边界见[第 14 票报告](../../../../.scratch/frontend-completion/ticket-14/report.md)。当轮Vite主chunk583.20kB提示保留，未执行任何Git命令。

第 13 票历史结果保留：完整审批输入及捕获提交跨重启保存、全量 GET 核实、未知结果人工继续、404 只读保留、按完整身份清理。显式 `gpt-6-luna / max` 执行唯一完整前端回归 **164 通过**，之后身份清理修复及新增测试的最终受影响专项 **91 通过**（含全部 13 项恢复测试）；分批 **7 个唯一真实 Tauri 用例各有最终通过证据**，真实 HTTP／SQLite／Graph 专项 **1 通过**。TypeScript、最终构建及 **6 个 Python 文件** Ruff 通过；预置 5173 服务与当前 dist 全部 **38 文件**字节一致。原生早期失败批次和夹具修复保留，不改算通过，不声称最终重跑前端全套或一次原生 7／7 全绿。Standards／Spec 无剩余硬问题；本票无后端产品、Rust、依赖或 API 变更，未重复完整后端回归。主 agent 已核对日志、请求、结果与截图，完整证据及七条验收对应见[第 13 票报告](../../../../.scratch/frontend-completion/ticket-13/report.md)。当轮用户明确禁止 Git 修改；未暂存、未提交、未切换分支。

第 12 票历史结果保留：真实请求按原顺序逐项批准／拒绝、完整只读参数、同 Run 提交、metadata 接受与互斥、真实审批处理记录及历史详情。显式 `gpt-6-luna / max` 完成最终 Node **152 通过**、唯一完整后端回归 **321 项：320 通过、0 失败／错误、1 Windows 符号链接权限跳过**，最终 HTTP 专项 **1 通过**；真实 Tauri 首轮 **12 项：0 通过、2 失败、10 错误**均止于环境连接，实机隔离首例 **1 通过**、其余 **11 项：9 通过、2 失败**，修复后最终定向 **7 通过、0 失败／错误／跳过**，分批共覆盖 12 个唯一原生用例，历史失败不改算通过。TypeScript／构建／产品 ty／新增三文件 Ruff 通过；新增 Graph 测试 ty 保留 **2 条 TypedDictLike 兼容诊断**，不算通过，官方状态类型可复现。Standards／Spec 无剩余硬问题；本票无后端产品或 Rust 改动。完整命令、八条验收对应证据、日志、截图与范围见[第 12 票报告](../../../../.scratch/frontend-completion/ticket-12/report.md)。

第 11 票历史结果保留：失败正文与实际原因原子保存、回滚保留结算所有者、不重跑 Graph、首终态竞争、错误色标记与完整原因查看、重开读取。显式 `gpt-6-luna / max` 完成后端新增专项 **12 通过**、最终串行完整回归 **313 项：312 通过、0 失败／错误、1 Windows 符号链接权限跳过**；前端全套 **140 通过**，样式修正后受影响专项 **6 通过**；真实 Tauri 首轮覆盖 **24 项：22 通过、2 失败**，随后本票最终 **1 通过**、旧 IME 原样隔离诊断 **1 通过**，未将隔离通过改算为完整批次全通过。专项与完整套件重叠，不相加。最终 TypeScript／构建、9 个唯一 Python 文件 Ruff、产品及新增测试 ty 通过；本票无 Rust 产品改动，未重复 Rust 构建或测试。Standards／Spec 0 项剩余硬问题。完整过程、历史失败、六条验收证据、日志、截图与覆盖边界见[第 11 票报告](../../../../.scratch/frontend-completion/ticket-11/report.md)。

第 10 票历史结果保留：后端专项 10 通过，最终串行全套 301 项中 300 通过、0 失败／错误、1 Windows 符号链接环境跳过；前端 Node 134 通过；真实 Tauri 单个 runner 串行新 4＋旧 19＝23 个唯一用例通过。TypeScript／构建／11 文件 Ruff／产品及测试范围 ty 通过，Standards／Spec 无剩余硬性问题。完整过程与历史失败见[第 10 票报告](../../../../.scratch/frontend-completion/ticket-10/report.md)。

第 9 票历史结果保留：前端首轮全套 121 通过，修复后受影响四个文件 56 通过（有重叠）；Rust 25 通过；后端 291 项中 290 通过、1 环境跳过；真实 Tauri 分批 19 个唯一用例通过。第 10 票原生回归捕获 Home 因亚像素锚点抖动被回写打断，窄修复后三个阅读位置用例均通过，未改变原断言。物理 Windows 输入、系统 IME、窗口边框及多尺寸联合验收仍归第 23 票；工作目录资源访问归第 14 票。历史[第 9 票](../../../../.scratch/frontend-completion/ticket-09/report.md)、[第 8 票](../../../../.scratch/frontend-completion/ticket-08/report.md)、[第 7 票](../../../../.scratch/frontend-completion/ticket-07/report.md)、[第 6 票](../../../../.scratch/frontend-completion/ticket-06/report.md)、[第 5 票](../../../../.scratch/frontend-completion/ticket-05/report.md)及[第 4 票](../../../../.scratch/frontend-completion/ticket-04/report.md)证据保留。

**保留的回归问题：**第4票的审批恢复结算超时在第5、6、7票完整回归中未复现，但未修改路径或确认根因，[旧问题](../../../../.scratch/approval-cleanup-test-timeout/issues/01-approval-resume-settlement-timeout.md)仍为needs-triage。第7票完整回归另出现空宿主环境变量分支的进程退出等待超时，正式隔离两次通过，原因未确认，见[新的独立问题](../../../../.scratch/desktop-environment-exit-timeout/issues/01-empty-host-environment-startup-exit.md)及[第7票后端报告](../../../../.scratch/frontend-completion/ticket-07/backend-report.md)。历史失败不改算通过。

第 8、9 票完整回归中上述两个正式用例均通过，未修改相关产品路径或确认根因，两份 needs-triage 记录继续保留。第 7 票的历史完整回归结果仍为 289 通过、1 错误、1 跳过，不能用本次通过覆盖，见[第 8 票后端报告](../../../../.scratch/frontend-completion/ticket-08/backend-report.md)及[第 9 票后端报告](../../../../.scratch/frontend-completion/ticket-09/backend-report.md)。

第 10 票较早完整回归再次出现审批结算同一 3 秒超时（299 通过、1 错误、1 跳过）；原生结束后的正式隔离两次为 1 通过／1 错误，最终单次串行全套未复现。未确认根因或与本票结算互斥变更的关系，旧问题继续 needs-triage，不能以最终通过抵消历史失败。两轮原生失败及第二轮发送前 Failed to fetch 也保留，详见[第 10 票报告](../../../../.scratch/frontend-completion/ticket-10/report.md)。

第 11 票完整后端回归未报上述两个历史超时，仍未确认根因。原生首轮新专项的纵滚夹具问题已修且保留断言；旧第 04 票 IME Enter 没有 POST、等待历史超时，原样隔离通过但原因与稳定性未知，新增[IME 待排查记录](../../../../.scratch/native-ime-enter-timeout/issues/01-composition-enter-no-post.md)。物理输入与系统 IME 验收仍归第 23 票。历史失败不改算通过。

实施由用户主导。ready-for-agent 表示任务描述自足；每票使用“待实施／实施中／待验收／已验收”记录实施进度，验收完成后才能将该票 Status 改为 done。后续使用 /implement 时仍遵守代码自主权约定。

共同要求：

- 每票完成用户可见的端到端路径，所需持久契约、公开接口／原生命令、客户端、UI 和边界验证在对应票内落实，优先复用既有能力。
- 各批新增组件从开始继承[设计规范](../../../../frontend/design.md)，实施阶段参照[八批计划](../tickets/006-interaction-acceptance.implementation.md)。阻塞边仅列完整标题的直接前提。
- 验证用户行为、公开请求／响应和已提交事实，优先使用现有 HTTP／SSE、BackendSession、Runtime 和原生验收入口，具体错误就地反馈并保留事实和输入。
- 状态权威、字段省略／null、目标失效、重试、Retry-After 和未知写入结果沿用定稿规格，所有写操作由用户主动，结果未知先 GET 核实。
- 每票的边界验证由实施者执行记录，最终联合验收补齐跨分支及真实 Tauri 证据；本轮票据的发布不代表实现或验收通过。

## 票据与直接依赖

| 序号 | 实施票据 | Blocked by |
| --- | --- | --- |
| 01 | [打开会话并核实运行状态](01-open-conversation-run.md) | 无，可立即开始 |
| 02 | [自动分页浏览带状态的会话列表](02-paginated-conversation-list.md) | [打开会话并核实运行状态](01-open-conversation-run.md) |
| 03 | [全量重建消息与当前运行事实](03-run-fact-reconstruction.md) | [打开会话并核实运行状态](01-open-conversation-run.md) |
| 04 | [原文发送并保留持久消息草稿](04-message-drafts-send.md) | [全量重建消息与当前运行事实](03-run-fact-reconstruction.md) |
| 05 | [断流后的有限 GET 恢复与手动重连](05-stream-recovery.md) | [全量重建消息与当前运行事实](03-run-fact-reconstruction.md) |
| 06 | [隐藏暂停读取并轮询会话状态](06-visibility-polling.md) | [自动分页浏览带状态的会话列表](02-paginated-conversation-list.md)；[原文发送并保留持久消息草稿](04-message-drafts-send.md)；[断流后的有限 GET 恢复与手动重连](05-stream-recovery.md) |
| 07 | [安全 Markdown、网页链接与完整内容查看](07-markdown-content-viewer.md) | [全量重建消息与当前运行事实](03-run-fact-reconstruction.md) |
| 08 | [完整呈现工具调用、结果与附加数据](08-complete-tool-records.md) | [安全 Markdown、网页链接与完整内容查看](07-markdown-content-viewer.md) |
| 09 | [恢复聊天阅读位置与自动跟随](09-chat-reading-position.md) | [全量重建消息与当前运行事实](03-run-fact-reconstruction.md) |
| 10 | [确认取消并保存已生成的中止正文](10-cancel-partial-message.md) | [原文发送并保留持久消息草稿](04-message-drafts-send.md)；[断流后的有限 GET 恢复与手动重连](05-stream-recovery.md)；[安全 Markdown、网页链接与完整内容查看](07-markdown-content-viewer.md) |
| 11 | [执行失败后保存已生成的中止正文](11-failure-partial-message.md) | [确认取消并保存已生成的中止正文](10-cancel-partial-message.md) |
| 12 | [逐项审批并继续同一运行](12-approval-resume.md) | [确认取消并保存已生成的中止正文](10-cancel-partial-message.md) |
| 13 | [恢复审批草稿并核实未知提交](13-approval-draft-recovery.md) | [隐藏暂停读取并轮询会话状态](06-visibility-polling.md)；[逐项审批并继续同一运行](12-approval-resume.md) |
| 14 | [自动预览工作目录内的本地图片](14-workspace-image-preview.md) | [隐藏暂停读取并轮询会话状态](06-visibility-polling.md)；[安全 Markdown、网页链接与完整内容查看](07-markdown-content-viewer.md)；[恢复聊天阅读位置与自动跟随](09-chat-reading-position.md) |
| 15 | [每次确认后用系统程序打开工作目录文件](15-workspace-file-open.md) | [自动预览工作目录内的本地图片](14-workspace-image-preview.md) |
| 16 | [导出已提交会话与完整工具记录](16-conversation-export.md) | [完整呈现工具调用、结果与附加数据](08-complete-tool-records.md)；[执行失败后保存已生成的中止正文](11-failure-partial-message.md) |
| 17 | [查看当前运行详情与真实累计用量](17-run-details-usage.md) | [隐藏暂停读取并轮询会话状态](06-visibility-polling.md)；[安全 Markdown、网页链接与完整内容查看](07-markdown-content-viewer.md) |
| 18 | [查看已提交运行事件与审批历史](18-run-events-history.md) | [查看当前运行详情与真实累计用量](17-run-details-usage.md) |
| 19 | [有限核实待结算用量](19-usage-settlement.md) | [查看当前运行详情与真实累计用量](17-run-details-usage.md) |
| 20 | [会话标题、日期时间与空态引导](20-conversation-titles-time-empty-state.md) | [自动分页浏览带状态的会话列表](02-paginated-conversation-list.md)；[原文发送并保留持久消息草稿](04-message-drafts-send.md) |
| 21 | [原稿风格的响应式导航与桌面偏好](21-responsive-navigation.md) | [自动分页浏览带状态的会话列表](02-paginated-conversation-list.md)；[原文发送并保留持久消息草稿](04-message-drafts-send.md)；[安全 Markdown、网页链接与完整内容查看](07-markdown-content-viewer.md)；[恢复聊天阅读位置与自动跟随](09-chat-reading-position.md) |
| 22 | [本地命令面板与受限全局快捷键](22-command-panel-shortcuts.md) | [查看当前运行详情与真实累计用量](17-run-details-usage.md)；[会话标题、日期时间与空态引导](20-conversation-titles-time-empty-state.md)；[原稿风格的响应式导航与桌面偏好](21-responsive-navigation.md) |
| 23 | [首版 Tauri 全流程与原稿实机验收](23-native-workflow-acceptance.md) | [恢复审批草稿并核实未知提交](13-approval-draft-recovery.md)；[每次确认后用系统程序打开工作目录文件](15-workspace-file-open.md)；[导出已提交会话与完整工具记录](16-conversation-export.md)；[查看已提交运行事件与审批历史](18-run-events-history.md)；[有限核实待结算用量](19-usage-settlement.md)；[本地命令面板与受限全局快捷键](22-command-panel-shortcuts.md) |

只列直接阻塞关系；各票的状态、实施进度和验收记录以对应文件为准。阻塞票验收完成并标记 done 后，其后继票进入可开始集合。
