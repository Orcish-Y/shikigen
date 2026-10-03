# 前端 PRD 与当前实现差距审计

初始代码审计：2026-10-03。规划状态更新：2026-10-04。目标：以完整 PRD 为依据，梳理前后端共同需要补齐的能力，形成实施前的决策地图。用户主导应用代码实现，下文代码事实未因规划定稿改写为已完成。

依据：[前端 PRD](frontend-prd.md)、[当前设计规范](../../frontend/design.md)、FastAPI 路由、消息/SSE 契约、React 组件与 Tauri 宿主代码。路线入口：[前端补全决策地图](../wayfinder/frontend-completion/map.md)。

后续已确认的实施目标见[会话与运行查询契约](../wayfinder/frontend-completion/tickets/001-run-discovery.contract.md)、[运行投影与恢复契约](../wayfinder/frontend-completion/tickets/002-run-projection.contract.md)和[审批与取消交互契约](../wayfinder/frontend-completion/tickets/003-approval-cancel.contract.md)。这些决策不表示审计所列缺口已经实现。

用户补充的中止消息保存、本地图片预览与文件确认打开已纳入首版。[消息、工具、导出与本地资源契约](../wayfinder/frontend-completion/tickets/004-message-tools-export.contract.md)已完整确认，消息呈现、字段、接口细则与导出格式均已定稿，实施待完成。

[运行详情、用量与事件契约](../wayfinder/frontend-completion/tickets/005-run-details.contract.md)已完整确认：自动快照与按需事件读取、累计用量和结算提示、受限后续核实、真实时间线及恢复入口均已定稿，应用接入与新增只读查询仍待实施。

2026-10-04 [交互与验收契约](../wayfinder/frontend-completion/tickets/006-interaction-acceptance.contract.md)和[八批实施与验收顺序](../wayfinder/frontend-completion/tickets/006-interaction-acceptance.implementation.md)已完整确认。七项首版规划票据及地图关闭；代码缺口和未验收项继续保留，决议见[交互与实施收尾决议](../wayfinder/frontend-completion/tickets/006-interaction-acceptance.resolution.md)。

这是代码与文档审计，没有运行功能测试、真实模型任务或审批操作。初次检查只能查看 2026-09-24 归档截图；2026-10-03 用户补充[菜单展开原稿](../../design/demo-菜单展开.html)、[菜单折叠原稿](../../design/demo-菜单折叠.html)、[项目展开截图](../../design/pic/展开.png)及[项目收起截图](../../design/pic/收起.png)，要求尽量贴近原稿。已完成桌面两态的静态对照，具体比例、差异和待补证据见[视觉复核记录](../wayfinder/frontend-completion/tickets/007-native-style-baseline.evidence.md)。直接原生控制仍不可用，其余视口及完整交互尚未验收。

用户随后确认以原稿和已有桌面画面定稿样式基准，其他实机检查在实施后完成，见[视觉基准决议](../wayfinder/frontend-completion/tickets/007-native-style-baseline.resolution.md)。视觉规划票据已关闭，所有未观测项目仍保留在后续验收责任中。

## 1. 做得好的部分

当前前端已经超出静态模板阶段。Windows Tauri 的真实业务链路和浏览器示例预览是两种运行模式，不能混为一谈。

| 已有能力 | 当前证据 | 可保留的边界 |
| --- | --- | --- |
| 后端托管、动态地址、手动重试 | [宿主入口](../../frontend/src-tauri/src/lib.rs)、[后端状态 hook](../../frontend/src/useBackendState.ts) | Rust 持有后端生命周期，React 只消费状态；页面刷新不启动另一个后端 |
| 创建、列出和读取真实会话 | [HTTP 客户端](../../frontend/src/backend-client.ts)、[会话 hook](../../frontend/src/useConversations.ts) | 业务请求通过当前 BackendSession 的地址与取消信号发送 |
| 显式发送与 fetch SSE | 同上 | POST 只在用户发送时发生，发送断连后使用 GET 读取，没有自动重发任务 |
| delta 与完整消息合并 | [receiveFor](../../frontend/src/useConversations.ts) | 以 seq 排序并替换预览，完整消息优先，不要求序号连续 |
| 切换会话关闭观察 | 同上 | AbortController 关闭 HTTP 观察，不等于取消后台 Run |
| 一条已有恢复路径 | 同上 | 读取历史消息后取最后一条消息的 run_id，GET 重建并跟随该 Run |
| 基础用量显示 | [App](../../frontend/src/App.tsx) | 运行详情已展示真实输入/输出 token，缺失值显示未知 |
| 页面骨架与本地交互 | [Sidebar](../../frontend/src/components/Sidebar.tsx)、[Conversation](../../frontend/src/components/Conversation.tsx)、[Overlay](../../frontend/src/components/Overlay.tsx) | 双侧栏、过滤、草稿隔离、折叠偏好、命令面板、代码复制、导出、原生 dialog 可继续复用 |
| Windows 单实例与托盘 | [desktop.rs](../../frontend/src-tauri/src/desktop.rs) | 正常关窗隐藏，显式退出清理后端；托盘失败有提示 |

浏览器直接访问 Vite 时，isTauri() 为 false，不订阅宿主，不生成真实 BackendSession，展示 demoSessions。这是当前明确的预览行为，不是 HTTP 接入失败。Tauri 窗口就绪后才走真实会话链路。

## 2. 系统中各层的位置

~~~mermaid
flowchart LR
    Host["Tauri 宿主：进程、托盘、启动状态"] -->|"invoke / backend-state-changed"| UI["React 工作台：用户操作与事实投影"]
    Host -->|"托管"| API["Python / FastAPI"]
    UI -->|"HTTP / fetch SSE"| API
    API --> Services["Runtime：Thread / Run / 观察 / 审批 / 取消"]
    Services --> Facts["持久 Run、事件与用量"]
    Services --> Execution["Graph 执行、工具与 checkpoint"]
~~~

**做什么：**补齐界面上的审批、取消、恢复与观察，把缺失的只读查询经 Runtime 暴露给前端。

**为什么：**后端执行能力已经存在，但部分事实尚未进入前端状态或缺少用户操作入口。前端不能从连接结束、按钮状态或示例数据推断执行结果。

**用什么 API：**业务继续使用现有 HTTP/SSE；桌面启动与日志继续使用现有 Tauri invoke。新页面复用当前工作台外壳与视觉 token，无须为补全 PRD 更换通信方式。

术语沿用已有代码：Thread 是持久会话；Run 是一次用户任务；同一 Run 可以经历多次执行和审批恢复；RunExecution 是进程内的一次执行；观察连接是读取事实的连接；Interrupt 是一组待人工决策的请求。宿主 ready、观察连接已建立、Run running 是三个不同事实。

## 3. 已经存在的后端接口

路由依据：[thread.py](../../app/routes/thread.py)、[run.py](../../app/routes/run.py)。以下 8 个业务接口均已存在，不应重复开发。

| 做什么 | API | 数据 / 当前前端使用 |
| --- | --- | --- |
| 列出会话 | GET /api/threads | 按更新时间倒序；前端已使用 |
| 创建会话 | POST /api/threads | 返回 thread_id；前端已使用；当前 HTTP 无标题请求体 |
| 读取会话消息 | GET /api/threads/{thread_id}/messages | 返回 data 下的持久消息，包含原 run_id 与 seq；前端已使用 |
| 发起任务 | POST /api/threads/{thread_id}/stream | message 文本输入，返回 SSE；前端已使用 |
| 读取单次 Run 消息 | GET /api/threads/{thread_id}/runs/{run_id}/messages | 已有 API，前端尚未封装；首版不一定需要独立入口 |
| 重建并跟随已知 Run | GET /api/threads/{thread_id}/runs/{run_id}/stream | 全量重建；已有前端观察方法；不支持 query、cursor、Last-Event-ID |
| 提交全部审批并恢复 | POST /api/threads/{thread_id}/runs/{run_id}/approval-decisions | 返回同一个 run_id 的新 SSE；前端没有方法与操作面板 |
| 取消 Run | POST /api/threads/{thread_id}/runs/{run_id}/cancel | 返回 data: RunSnapshot；前端没有方法与操作入口 |

桌面桥接已有 get_backend_state、retry_backend、get_backend_logs、get_tray_error，以及 backend-state-changed 事件。桌面就绪探测的 /health/ready 服务于本次宿主启动身份检查，不能替代当前会话的 SSE 连接状态。

取消响应中的 RunSnapshot 使用 id；SSE metadata 使用 run_id。补客户端时需要明确转换，不能直接把两种响应都当成现有 Run 类型。

SSE 依据：[run_contract.py](../../app/run_contract.py)。已有 metadata、delta、event、error；event 分 message、lifecycle、approval。完整事件携带 seq、created_at、event_type。前端目前没有完整保留这些事件信息。

## 4. 需要补齐的前端能力

优先级保留初次审计的分类：P0 影响执行控制或恢复；P1 对应首版完整展示与交互；P2 为体验细节或后续增强。首版选入范围及实施依赖以已确认契约和八批实施顺序为准，不因表中优先级漏掉已纳入的命令／快捷键等要求。

| 优先级 | 做什么 / 对应 PRD | 当前缺口 | 为什么 | API / 实现入口 |
| --- | --- | --- | --- | --- |
| P0 | 完整审批面板：7.4、验收 4/5 | approval payload 仅声明 unknown；receiveFor 没有处理 approval；只有“正在等待审批”的说明 | 任务中断后用户无法批准或拒绝，完整工作路径断开 | 现有 approval event 与 approval-decisions POST；逐项选择、参数折叠和草稿恢复见已定审批与取消交互契约 |
| P0 | 取消 running / interrupted：7.3、验收 6 | BackendSession 无 cancel 方法，Composer 没有取消按钮、确认和 pending 状态 | 用户无法主动结束仍在执行或等待审批的任务 | 现有 cancel POST；确认、请求互斥及返回真实终态的目标已定稿，仍待实施 |
| P0 | 观察连接状态：7.6、8、验收 3 | 顶栏和导航只看 Boolean(session)，没有 SSE connecting/open/closed/error 状态 | 宿主就绪并不表示当前观察成功；无法清楚解释断流 | fetch/reader 状态、metadata、lifecycle；宿主状态单独保留 |
| P0 | 已知 Run 的显式重连：9、11、验收 7/9/14 | 只有通用“刷新数据”；没有按 Run 保存恢复线索、分类重连与执行状态待确认视图 | 恢复操作必须只读，并说明服务端是否已接受任务 | 现有 GET Run stream + thread_id→run_id 的本地线索；配合下节新增定位接口 |
| P0 | HTTP 错误恢复：11、验收 9 | request 把所有非 2xx 转成 Error 文本，丢失结构化状态与 Retry-After | 409 要重建事实，422 要保留审批选择，503 要按服务端提示重试 | 保存 status、detail、Retry-After；区分观察错误与生命周期错误 |
| P0 | 发送失败保留草稿：7.3 | send() 同步返回已发起后立刻 updateDraft("")；后续 HTTP 失败不恢复；Workspace 在非 ready 时卸载或因 startupId 重新挂载，内存草稿会丢失 | 请求失败、接受状态未知或后端重启时，用户的原始输入不能丢失 | 已确认按会话保存草稿及待确认记录，接受 metadata 后才清空；见运行投影与恢复契约，仍待实施 |
| P0 | 取消／失败也保存生成正文：用户补充 | 未完成正文只在后端内存中积累；现有取消／失败结算不保存这些消息 | 重开会话和导出后仍需读取已经产生的内容及中止原因 | 后端消息接入与终态结算、待新增 AI generation_status；前端补读现有 Run messages，详见已确认消息契约 |
| P1 | 消息中的真实 Markdown/代码：7.2、验收 12 | 实际消息只按空段落渲染为 p；CodeBlock 只接收 demo 的 code 字段 | 模型返回的 fenced code、列表、表格不能按模板层级阅读或复制 | 已确认 Agent Markdown、用户原文、工具原文／JSON；安全渲染及真实代码复用当前样式，长内容内部滚动并完整复制 |
| P1 | 工具调用与结果关联：7.2、验收 12 | AI tool_calls 拼成正文；ToolMessage 独立当 Agent 行显示；没有按 tool_call_id 合并参数与结果 | 用户难以检查某次调用对应什么结果，也没有等待结果状态 | 同 Run tool_call_id 合并，按原调用顺序排列；默认折叠，失败首次展开结果；孤立结果保留 |
| P1 | artifact / content block 展示：7.2 | MessageContent 未声明 artifact；对象含 text 时直接取 text，其余字段不展示 | 后端保存了完整数据，界面不应在投影时丢失 | 明确 text 块按角色展示，额外字段及未知对象完整 JSON；非 null artifact 只读完整保留，详见消息契约 |
| P1 | 工具失败样式 | 工具失败仍复用 success 绿色勾号，只改变文字 | 状态图标与文字应一致 | ToolContent.status；沿用浅色组件并增加语义明确的错误态 |
| P1 | 本地图片与文件打开：用户补充 | 尚无工作目录资源 HTTP、图片读取和受控文件打开桥接；真实 Markdown 入口也未接入 | 自动显示工作目录内明确引用的图片，文件每次核实并确认后打开 | 待新增只读 workspace/resources 查询与图片响应、受控 Tauri 命令；已确认入口与目标，样式沿用现有详情层和 dialog |
| P1 | 完整运行详情：7.5、验收 8 | 只显示 Run ID、状态、输入与输出；缺会话 ID、复制、总 token、calls、by_model、usage_pending、时间和完整错误 | 首版承诺的排障与用量事实未展示完 | 已确认 SSE 与纯读快照共用投影，分别展示累计用量和结算；后续核实上限与样式见运行详情契约，待实施 |
| P1 | 生命周期与审批事件时间线：7.5 | hook 不保存事件；RunFrame 没有 created_at / event_type | 详情无法解释开始、审批、恢复、取消与失败的过程 | SSE event 与打开详情时的 events GET 合并，按 seq 去重；默认运行／审批，可包含消息，完整 JSON 可查看复制，目标已确认 |
| P1 | 历史栏用量摘要：7.1 | History 永远显示“暂无用量数据”，没有接收 run usage | 主页面摘要与详情中的真实值不一致 | 已确认进入会话读一次快照，“本次运行用量”与详情共用当前 Run 事实；未知、读取失败及待结算分别提示，待实施 |
| P1 | 会话标题、日期分组与时间：7.1、验收 13 | 真实会话一律 group=历史；summary 原样显示 updated_at；无标题时用 ID；未派生首条 Human 标题 | 真实数据接入后，模板已有的时间分组与可读标题退化 | 已定本地临时标题缓存与真实消息核实，不新增标题 PATCH；真实本地日期分组、七天起日期及完整时间入口，详见交互契约 |
| P1 | 列表与消息加载/空/失败状态：7.1、11 | 无 skeleton；空列表与过滤无匹配使用同一提示；列表失败显示主区通用错误 | 用户需要区分尚未读取、确实为空、过滤无结果和读取失败 | 现有 GET；独立列表/消息状态和原位重试 |
| P1 | Enter 与中文输入法：7.3、12 | textarea 无发送键盘处理；运行中输入仍可编辑，但没有完整说明及持久恢复 | 当前只能点按钮发送，输入需遵守最新交互选择 | 已定可编辑草稿、不排队／自动发送，trim 只判空、原文发送；不可发送时拦截 Enter，仅 Shift+Enter 换行，输入法优先，详见交互契约 |
| P1 | 流式滚动、回到底部：12 | 时间线没有底部位置判断、跟随或“回到最新”入口 | 输出变长时需要可持续观察，同时保留上翻阅读位置 | 已定首次最新、本次应用内切回恢复锚点；上翻停跟随、图片和布局不抢位置；本地状态，不新增 HTTP |
| P1 | 只导出已提交内容：7.6、验收 13 | 导出直接遍历 active.messages，包含当前 preview；真实导出未标明范围 | 临时 delta 不能被导出为已经提交的记录 | 点击时已加载的已提交快照，包含完整工具记录和中止正文；正常 Agent Markdown 可阅读，中止／未闭合正文原文保存，格式见已确认消息契约 |
| P2 | 命令面板与详情空态：7.6 | 无真实 Run 时“运行详情”仍能点；命令面板只有查找入口，没有直接列出已加载会话 | 操作应有明确可用性与数据边界 | 已定本地搜索操作与已加载会话、禁用原因及方向键／Enter／Esc；动作复用，无新增搜索 API |
| P1 | 平板主导航覆盖：6.3、7.7、验收 16 | 768–1279 的 CSS 一直隐藏 nav-label、固定 64px；折叠按钮改变状态但不打开 256px 覆盖导航 | 该宽度下不能完成 PRD 描述的展开操作 | 复用 mobilePanel / 遮罩与当前侧栏；无需修改宿主 |
| P2 | Cmd/Ctrl+B：7.7 | 快捷键只有 K 和 N，前景模态未屏蔽全局动作 | PRD 中的导航折叠快捷键尚未接入 | 已定 K／N／B 在输入中可用，输入法／长按／模态限制；仅 K／B 关闭各自面板，保留按钮 |
| P1 | 可访问性与状态反馈：12 | 业务状态没有集中 aria-live；触控目标仍多为紧凑尺寸；危险操作的 pending 尚未实现 | 新审批/取消操作需可通过键盘完成，并可确认操作状态 | 原生 button / dialog、现有焦点样式、适量状态播报 |
| P1 | 主按钮 hover | 通用 button:not(:disabled):hover 将背景变为浅灰，优先级高于 .primary-button；文字仍为白色 | 需要保持品牌主按钮的可读交互态 | 保留靛蓝风格，给主按钮明确 hover；当前仅静态规则判断，实机待核对 |

当前纯文本经 React 渲染，不能将“没有 Markdown”误报成已有 HTML 注入。安全 Markdown 渲染是接入富文本时新增的要求。

## 5. 后端缺失与 PRD 的关系

### 5.1 首版查询目标仍未暴露

已确认的实施目标见[会话与运行查询契约](../wayfinder/frontend-completion/tickets/001-run-discovery.contract.md)。下表保留审计时的后端事实，并列最终查询目标；已确认目标尚未实现。

| 做什么 | 当前后端事实 | 为什么 | 已确认目标，尚未实现 |
| --- | --- | --- | --- |
| 会话分页与当前 Run 定位 | threads HTTP 为裸列表，尚无分页和 run_id／run_status 摘要；历史消息可取最后 run_id，缺外层 run_status | 列表显示中文状态，打开会话从历史定位，避免另设 active_run／latest_run 包装 | GET /api/threads 固定 20 条游标页、真实更新时间倒序；历史外层增加 run_status；首版不新增独立 Run 列表 |
| 读取 Run 快照 | RunService.read_run 已存在且包含恢复校验，没有对应纯读 HTTP | 普通刷新、错误解释与当前运行详情直接获取持久快照，查询需隔离执行／校验写入 | 新增纯读 GET /api/threads/{thread_id}/runs/{run_id} |
| 读取 Run 持久事件 | RunService.list_run_events 已存在，没有对应 HTTP | 让详情与后续追踪视图能只读查询，不依赖为了读取历史而保持 SSE | 新增纯读 GET /api/threads/{thread_id}/runs/{run_id}/events，完整公开事件按 seq 升序 |

当前前端已经从最后一条持久消息取得 run_id，因此刷新或本地状态丢失并非一律无法恢复。最终方案继续通过历史定位，running／interrupted 使用现有 GET Run stream 重建并从 metadata 核实；纯读 JSON 用于普通查询与详情，不替代审批重建。本地 run_id 只是线索，不能替代服务端事实。

### 5.2 用户补充的首版后端与宿主缺口

| 做什么 | 当前事实 | 为什么 | 已确认目标，尚未实施 |
| --- | --- | --- | --- |
| 取消／失败保存已接入正文 | RunEventIngestor 的未提交正文仅存在内存；取消和失败结算没有封存完整消息 | 终态和消息共同提交，避免返回取消成功却丢失正文 | AI generation_status；保留 message_id 与预留 seq 的原子结算；现有历史、Run messages 和 SSE 提供完整消息 |
| 工作目录与文件元数据查询 | 文件工具已有 workspace_root 与路径范围检查，没有资源 HTTP | 图片读取与文件确认使用同一实际根目录及目标 | 待新增 GET /api/workspace 与 GET /api/workspace/resources/resolve?path=... |
| 本地图片响应 | 后端尚无图片资源接口，Tauri 未配置本地资源协议 | 仅读取核实后的目录内图片，局部反馈错误 | 待新增 GET /api/workspace/resources/{resource_id}/image；前端按当前租约读取 Blob |
| 系统浏览器与确认打开文件 | 宿主尚无 opener 和这些受控命令 | 明确打开网页／文件的意图，核实确认中的实际目标 | 待新增 open_web_url、prepare_workspace_file_open、open_prepared_workspace_file |

这些目标不要求另建文件管理页，不把 artifact 或任意 JSON 自动识别为文件。详细数据、竞态与交互以已确认消息契约为准；实现仍由用户主导。

### 5.3 PRD 第 14 节的 P1 扩展

这些不是原首版验收失败。若启用对应独立页面，需要前后端共同补契约，再接入页面。

| 能力 | 当前支持到哪里 | 缺什么 / 为什么 | API 或决策入口 |
| --- | --- | --- | --- |
| 会话重命名 | Python 创建服务和数据库有 title；当前 HTTP 不接受 title，也没有更新方法 | 编辑标题不能仅改本地显示后声称保存 | 候选 PATCH /api/threads/{thread_id}；决定校验、更新时间与并发行为 |
| 会话搜索、归档、删除 | 前端只有已加载标题过滤 | 服务端搜索范围、软/硬删除、Run 与 checkpoint 级联及运行中限制尚未定义 | 先定生命周期语义，后定查询/更新/删除 API |
| 工具与 MCP 能力页 | ToolRegistry、内置工具与 MCP 加载已有 | 没有面向前端的能力目录、启用状态或配置管理 API；工具调用结果不代表完整工具目录 | 候选只读 capabilities/tools API；管理操作与只读目录分别决策 |
| 系统设置 | 配置模型/文件加载已有；启动重试读取配置 | 没有前端可读的配置快照、受控写入和变更生效契约 | 决定字段可见范围、编辑范围及重启/后续 Run 生效规则；不直接把完整配置原样返回 |
| 独立运行日志与追踪 | 当前 Run 的持久事件和宿主启动 stderr 已有 | 没有全局 Run 查询与独立页面；启动日志不等于某次 Run 的持久业务事件 | 先补 Run 查询，再决定页面的时间范围与过滤；启动日志仍走 get_backend_logs |
| 子 Agent 委派视图 | task 工具等待子 Agent 返回，父 Run 能看到该工具结果 | 没有独立子 Run 历史、结构化任务关系与子状态事件 | 新增委派事件/关系契约后再建设结构化视图 |
| Goal 与 checkpoint 视图 | GoalMiddleware、checkpoint 与恢复已有 | Graph 内部状态不是已暴露的产品查询契约 | 先定产品状态与只读数据范围，再决定接口；不能把 Run interrupted 当 Goal paused |
| 模型切换、reasoning、联网策略、附件 | 当前 HTTP 只接收 message；reasoning 是预留字段 | 没有对应请求/执行/事件契约；不得启用没有作用的开关 | 按需新增明确契约，再恢复对应控件 |
| 上下文占用、工具耗时、吞吐率、费用 | 只有已知 token 用量，没有价格或这些指标 | 需要采集来源和一致的数据口径 | 先定义计量，再展示；不以 token/calls 推算准确账单 |

已有工具：get_current_time、add、read_file、write_file、list_dir、grep、bash、web_fetch_tool、web_search_tool、task，以及实际配置成功加载的 MCP 工具。能力依据是工厂装配，具体可用性仍取决于配置、凭证及运行环境。

额外发现：现有 GoalMiddleware 识别以 /goal 加空格开头的文本，默认最多续跑 5 次。这可经现有 message API 触发；PRD 没有介绍这项输入约定。它不等于已有 Goal 管理页、进度接口、跨进程调度器或暂停/恢复控制。

当前标准主 Agent 审批 write_file、bash；子 Agent 通过独立 create_agent 构建，没有自动继承这套审批 middleware。前端只能展示后端实际发送的审批，不能宣称所有子 Agent 或 MCP 副作用操作均受同一审批策略保护。

## 6. PRD 与文档需要修正的描述

| 位置 | 需要修正的内容 | 原因 |
| --- | --- | --- |
| PRD 第 2/6.4 节 | Tauri 从示例内容变为当前实际宿主；增加宿主状态与观察连接的区分 | 2026-10-02 已接入真实 Tauri 托管后端 |
| PRD 第 4/7.1/9/14 节 | 增补“通过最后一条持久消息的 run_id 恢复”的现有路径，保留缺少直接查询的说明 | 当前实现不再完全依赖浏览器本地映射 |
| PRD 能力矩阵 | 分别列后端支持、前端接入、未验收项 | 后端已有 API 不代表前端操作已交付 |
| 原 frontend/design.md | 更新“仅页面框架”“HTTP/SSE 待接入”等阶段描述 | 原设计文档停留在 2026-09-24；本次已按代码更新 |
| PRD 的原型相对路径 | 已修正为从 docs/frontend 指向根 design 的 ../../design/ | 文件移动后 ../design/ 指向错误位置；原型本身仍存在 |
| docs/README 与历史工作记录的 PRD 链接 | 总导航已修正；历史工作记录中的旧路径仍应按当前位置理解 | 当前文件实际位于 docs/frontend/frontend-prd.md，原 docs/frontend-prd.md 已不存在 |
| NOTES.md | 当前能力清单落后于代码，不能用作完成度判断 | Token/Web/Goal/子 Agent 与桌面接入已经有实现；学习进度由用户主导维护 |

本次保留原 PRD 的功能正文，使用本审计记录差距；不把建议中的产品决策直接改写为已确认需求。设计规范已更新到当前代码依据。

## 7. 决策结果与后续边界

1. **Run 发现 API：**已定会话分页摘要与历史状态，保留最后 run_id 的发现链路，沿用 SSE 恢复并新增纯读快照／事件；首版不新增 Run 列表或 active_run／latest_run 包装。
2. **完整 PRD 的页面范围：**已确认前后端一起补齐首版聊天工作台和后端恢复接口；工具、设置、追踪等独立页面留到后续。第 4 节明确不支持的能力不自动变成首版承诺。
3. **运行中草稿及剩余交互：**已定执行期间可编辑并保存草稿、结束后手动发送；输入原文、Enter／IME、自动分页、标题／时间、阅读位置、命令与窄屏规则以交互契约为准，替代旧 PRD 不一致建议。
4. **配置变更与工具策略：**若纳入设置与工具管理，变更何时生效、对既有 Run 的影响与数据边界需要先决策。
5. **新页面布局：**全局页面保留应用栏与主导航；会话历史仅在聊天或以 Thread 为范围的视图中出现。原稿及项目桌面两态视觉已确认，新组件遵循 design.md，实机复核在实施后完成。

## 8. 推荐推进顺序与完成条件

按已确认的[八批实施与验收顺序](../wayfinder/frontend-completion/tickets/006-interaction-acceptance.implementation.md)推进，先完成查询与投影，再接入依赖其事实的操作；中止正文结算先于保存承诺，资源与受控桥接先于预览／打开。各批从开始就遵守样式基准，独立模块可提前实现；独立管理页面另行规划。

查询、投影与恢复、审批与取消、消息／工具／导出与本地资源、详情／用量／事件、原稿与桌面截图视觉，以及剩余交互与实施／验收顺序均已定稿，七项子票据与[地图](../wayfinder/frontend-completion/map.md)关闭。用户已确认首轮补齐首版聊天工作台与后端恢复接口，包含中止消息保存、本地图片预览与文件确认打开；独立页面留后续。应用实现与剩余实机检查待完成，不能从规划关闭推断通过。

后续实现验证需要覆盖：逐项审批与拒绝、同 run_id 恢复、运行/审批时取消、重复/迟到请求、断连与服务端已接受但客户端未知、重放去重、用量未知和受限结算核实、模型分项、详情局部失败、真实事件与终态竞争、中止正文保存和重开恢复、完整工具记录、已提交导出、工作目录资源、文件确认及目标变化、会话隔离，以及 1440×900、1280×800、1024×768、390×844 的操作可达性。本次没有执行这些验证。
