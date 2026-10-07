> 归档于 2026-10-07；正文状态与命令属于原开发阶段。当前完成情况见 [开发交接](../../../../../development-handoff.md)。相对路径链接已迁移；代码块中的旧 scratch 路径需按归档路径调整。

# 第 23 票：Tauri 联合验收与修正报告

日期：2026-10-07。票据：[首版 Tauri 全流程与原稿实机验收](../../../../../wayfinder/frontend-completion/implementation/23-native-workflow-acceptance.md)。**八项验收已核对完成，本票已验收并标记 done；实施索引第 1–23 票均已完成。**

## 本轮改动

- 取消 POST 尚未确认时，SSE 的 `completed`／`cancelled`／`error` 只能更新运行事实，不能清除取消的 pending／unknown。保留待确认提示与发送限制，直到本次 POST 有效快照或后发 GET 核实；新增六种终态与通知顺序竞态断言。
- 聊天主时间线获得焦点时，End 明确定位最新并恢复跟随。输入控件、代码／JSON 内滚区与组合快捷键仍各自处理按键。
- 将可调用接口统一命名为 `scrollToLatest`，阅读状态操作命名为 `followLatest`，同步组件与测试。
- 联合验收复用真实 Tauri、应用托管 Python、HTTP／SSE 与 SQLite；新增真实模型、生产程序只读路径、四档原生窗口帧、Windows 输入与系统剪贴板取证。
- 修正验收夹具的中文字段、消息区域定位、会话切换等待、按钮检查与点击竞态、事件／快照请求计数、SSE instrumentation 作用域及 Windows 输入；保留原断言与所有失败产物。

产品源码只涉及前端状态与阅读逻辑；本票未修改后端／Rust 产品代码、API、依赖或根配置。未执行任何 Git 命令，未暂存或提交。已关闭的父地图保持原状态。

## 验证分工与范围

最终测试与两个审查轴均显式使用 **`gpt-6-luna / max`**。主 agent 负责设计、产品及测试修复，并核对原始结果。前端／Rust与后端独立回归并行；9238／45200 共享端口、原生前景窗口及生产程序验收串行。

上轮验证子 agent 曾因工作区额度耗尽停止。本次恢复轻量子 agent，完成剩余定向回归与生产路径；追加范围为尚未通过或最后发生变化的检查，没有重复已通过的付费模型任务与完整套件。默认保存 UI 探针的历史失败保留；修正夹具非默认询问偏好后，默认下载原用例已证明完成与退出留存，真实 IME 选词与发送也已通过。增强 OSK 点键探针未通过，直接并存可达性另行验证。

5173 的原有服务 PID `23344` 仅经逐文件 dist 字节核实后复用；不停止该服务。每批仅清理由验收入口拥有的宿主及其后代。

## 完整与定向回归

| 范围 | 实际结果 | 命令与原始证据 |
| --- | --- | --- |
| 完整后端 | 334 执行：333 通过，0 失败／错误，1 Windows 符号链接权限跳过 | 根目录 `.venv/Scripts/python.exe -m unittest discover -s tests -v`；[原始日志（原始产物已删除）](../../../README.md#已删除的材料)、[结果（原始产物已删除）](../../../README.md#已删除的材料) |
| 完整前端 | 修复后 Node 269／269 通过，无失败／跳过 | `frontend` 目录 `node --import tsx --test tests/*.mjs`；[原始日志（原始产物已删除）](../../../README.md#已删除的材料)、[执行结果（原始产物已删除）](../../../README.md#已删除的材料) |
| 最后命名调整后 | 阅读位置与取消专项 20／20 通过；TypeScript 退出 0 | `frontend` 目录 `node --import tsx --test tests/chat-reading-position.test.mjs tests/run-cancel.test.mjs`、`node node_modules/typescript/bin/tsc --noEmit`；[结果（原始产物已删除）](../../../README.md#已删除的材料) |
| 最终 Vite 构建 | 退出 0，38 文件、1,049,454 字节 | `frontend` 目录 `node node_modules/vite/bin/vite.js build`；[构建结果及哈希（原始产物已删除）](../../../README.md#已删除的材料)、[日志（原始产物已删除）](../../../README.md#已删除的材料) |
| 完整 Rust | 35／35 通过，无失败／忽略 | `frontend/src-tauri` 目录 `cargo test --locked -- --test-threads=1`；[结果（原始产物已删除）](../../../README.md#已删除的材料)、[日志（原始产物已删除）](../../../README.md#已删除的材料) |
| Rust 格式／lint／入口编译 | 格式、clippy、两个验收 example 与生产 executable 构建均退出 0 | [前端／Rust 报告](../../../frontend-history.zip)（包内：`docs/archive/2026-10-07/development/frontend-completion/ticket-23/validation/frontend-rust/final-1/report.md`）及其逐命令结果 |
| 产品 Python 类型 | 退出 0，范围为 `app packages/harness/shikigen` | 根目录 `.venv/Scripts/python.exe -m ty check app packages/harness/shikigen`；[结果（原始产物已删除）](../../../README.md#已删除的材料) |
| 本票 Python lint／格式 | 最后焦点／剪贴板修正后 13 文件检查均退出 0，入口导入与三方法清单通过 | [原 13 文件检查（原始产物已删除）](../../../README.md#已删除的材料)、[本次续验收报告](../../../frontend-history.zip)（包内：`docs/archive/2026-10-07/development/frontend-completion/ticket-23/validation/native/resume-report.md`） |

最终构建清单 SHA-256：`fdc6b6b595a5531ae8553c6bdb037f621dce64fbc3f169e305bc06737d81c83f`。前一修复构建为 `cc1617aface0a4364f6d440304f235627c89c087a3bfbcd7eb79a07160c93c22`；每批使用的构建分别记载，不把旧批次改记成最终版本。

Vite 主 JS chunk 为 642.19 kB／gzip 195.09 kB，超过 500 kB 的构建告警保留。初始全仓 Ruff check 为 379 条诊断、format 为 64 文件待格式化：属于较早源码快照与仓库既有问题，未修整个仓库，不能宣称全仓 lint 通过。当前票据文件检查独立记录。

原审批恢复结算超时、空环境进程退出超时在本次后端全套中通过，但没有确认根因，既有 `needs-triage` 记录继续保留。原生 IME 间歇问题亦未因本轮单测通过而关闭。

## 原生离线历史与本次续验收

| 批次 | 实际结果 | 范围与证据 |
| --- | --- | --- |
| native `final-1` | 105 执行：95 通过、8 失败、2 错误、0 跳过 | 完整唯一用例基线；[摘要（原始产物已删除）](../../../README.md#已删除的材料)、[逐项结果（原始产物已删除）](../../../README.md#已删除的材料)、[日志（原始产物已删除）](../../../README.md#已删除的材料) |
| native `final-2` | 19 执行：14 通过、2 失败、3 错误、0 跳过 | 修复构建：客户端、恢复、取消四项、文件失效、详情及阅读两项等通过；[摘要（原始产物已删除）](../../../README.md#已删除的材料)、[逐项结果（原始产物已删除）](../../../README.md#已删除的材料) |
| native `final-3` | 3 执行：0 通过、3 失败、0 跳过 | 分页焦点等待；Windows 原文中的换行没有进入；复制动作前误把已保存内容块数组当字符串。均保留失败；[摘要（原始产物已删除）](../../../README.md#已删除的材料)、[日志（原始产物已删除）](../../../README.md#已删除的材料) |
| native `final-4` | 8 唯一用例：5 通过、3 失败；剪贴板失败用例另有 1 个清理错误 | Client 两项与 ChatReading 三项通过；分页／Windows 输入仍未获得 OS 前景，剪贴板比对及 OLE 恢复失败；[逐项结果（原始产物已删除）](../../../README.md#已删除的材料)、[原始日志（原始产物已删除）](../../../README.md#已删除的材料) |
| native `final-5` | 3／3 通过，0 失败／错误／跳过，退出 0 | 窄修正后的 Windows 聚焦、输入与完整系统剪贴板；[逐项结果（原始产物已删除）](../../../README.md#已删除的材料)、[摘要（原始产物已删除）](../../../README.md#已删除的材料)、[续验收报告](../../../frontend-history.zip)（包内：`docs/archive/2026-10-07/development/frontend-completion/ticket-23/validation/native/resume-report.md`） |
| native `default-download` | 用例 1／1 通过；后验源文件不存在，保存持久性仍待核实 | 不覆盖浏览器下载策略，取得真实完整字节及归档副本；退出即时断言通过不等于后续留存。[摘要（原始产物已删除）](../../../README.md#已删除的材料)、[命令（原始产物已删除）](../../../README.md#已删除的材料) |

不同批次有重叠，不累加为一次全绿结果。`final-2` 的审批定位用例实际失败点是点击“刷新数据”时的按钮状态竞争，主 agent 已核对完整回溯；此前报告的“未找到处理审批”不是准确的失败位置。`final-3` 中中文输入本身正确，丢失的是 Unicode LF 换行；不能把终端编码显示差异误报为产品乱码。

Windows `final-4` 的实际点击命中另一个浏览器渲染子窗口，并非 Tauri 标题栏；[前景元数据（原始产物已删除）](../../../README.md#已删除的材料)保留该事实。最新修正临时关联输入队列并解除，只对验收拥有的窗口请求前景；鼠标位置命中的根窗口必须等于验收目标，否则失败退出，防止点击其他应用。输入使用 Windows `SendInput`。

剪贴板 `final-4` 的 OLE 恢复报 `CloseClipboard` 错误，**该历史批次未证明原剪贴板成功恢复**。最新夹具改为在复制前把所有可恢复内存格式完整物化并私下保留；遇不可恢复格式先失败、不复制；复制后恢复全部格式并逐一核对。OS `CF_UNICODETEXT` 按[微软格式约定](https://learn.microsoft.com/en-us/windows/win32/dataxchg/standard-clipboard-formats)严格比较完整 CRLF 文本，失败只留哈希、长度与换行计数，不记录原私人剪贴板正文。`final-5` 已实际通过完整值比对和本次复制前原格式恢复，不倒推历史批次也已恢复。即便自动用例通过，也不会替代人的物理键盘、系统 IME 候选窗或触摸屏操作。

最后八个受影响唯一用例分批各有通过证据：`final-4` 的客户端两项与聊天阅读三项、`final-5` 的分页／Windows 输入／剪贴板三项。没有把重叠批次相加，也没有将完整 105 项历史基线改称一次全绿。所有本票初始未通过项中，默认保存 UI 探针仍无通过证据。

## 真实模型与生产程序

真实模型五个唯一场景均已有通过证据。配置使用现有 DeepSeek provider／`deepseek-v4-flash`，实际 `app.desktop`、runtime、工具和 checkpoint，隔离 workspace／SQLite；无模型回答或工具执行替身。窗口使用 `backend_window.exe` 验收宿主，与下方生产 executable 只读验证分别记录。

| 在线场景 | 实际结果 | 身份与证据 |
| --- | --- | --- |
| 普通任务 | 真实回答、human／AI 持久消息及用量通过 | [result（原始产物已删除）](../../../README.md#已删除的材料) |
| `write_file` 审批 | 实际退出／重开后恢复审批草稿，GET 核实，同 Run 继续，写入一次 | [result（原始产物已删除）](../../../README.md#已删除的材料) |
| `bash` 拒绝 | 拒绝后同 Run 继续，无目标文件副作用 | [result（原始产物已删除）](../../../README.md#已删除的材料) |
| running／interrupted 取消 | 两种运行状态均真实取消，待审批写入未发生 | [result（原始产物已删除）](../../../README.md#已删除的材料) |
| 断流／刷新／隐藏／重开 | POST 断流后 GET 恢复，草稿刷新保留，后台完成、原生显示与重开恢复，无重复 human | [result（原始产物已删除）](../../../README.md#已删除的材料) |

每个 result 含 `startup_id`／`thread_id`／`run_id`、运行快照与持久事实。在线最后一项的首次执行在模型 POST 前因两段 instrumentation 的顶层 `const original` 冲突失败；IIFE 隔离后只重跑这一项，旧失败保留。自然完成与取消竞争、未知结果及故障注入另由可控离线用例验证，不冒充供应商故障。

生产 `final-1` 已验证真实 `shikigen-desktop.exe`：应用拥有实际 Python 后代进程；端口 43127 被本例预约后实启 43128；health startup 一致；关闭隐藏、第二实例退出 0 并显示同窗，Python 进程树相同；实际 native tray 菜单退出通过。根配置／用户数据库保持原路径，采集请求全为 GET，没有创建用户会话或调用模型。

生产 `final-2` **1／1 通过**，实际 owned Win32 tray 菜单“打开主窗口”、同窗／同 startup、再次隐藏后二次启动、相同 Python 后代及托盘退出均有结果；startup `92128bc1-0c65-4af9-b267-610001b6b186`，实际地址 `127.0.0.1:43128`。退出后 10 个记录的 owned 进程均已消失，9238／45200 释放，5173 原服务保留。该入口是 OS 消息派发，不能称为人的托盘鼠标操作。[生产最新结果（原始产物已删除）](../../../README.md#已删除的材料)、[逐项结果（原始产物已删除）](../../../README.md#已删除的材料)、[清理记录（原始产物已删除）](../../../README.md#已删除的材料)。本票不验收安装包、签名与 Python 分发。

## 原稿与四档窗口证据

已用 Win32 `PrintWindow(PW_RENDERFULLCONTENT)` 捕获含原生标题栏的完整窗口帧，实测 CSS 内容区 1440×900、1280×800、1024×768、390×844；DPR 1.5、DPI 144，分别对应 client 像素 2160×1350、1920×1200、1536×1152、585×1266。完整帧像素包含标题栏与边框，另存于 JSON，不能与 CSS 尺寸混用。

[四档尺寸、几何与窗口帧（原始产物已删除）（原始产物已删除）](../../../README.md#已删除的材料)。桌面展开／收起保留 256／64 导航、256 会话栏与 Geist 字体、浅色背景、紫色主操作；主 agent 已对照项目原稿与现有桌面截图。原生完整回归包含响应式导航四场景；本票产品修正未改变 CSS 风格或尺寸。

## 追加的 Windows 操作验证

仍由 `gpt-6-luna / max` 串行执行，真实 Win32 输入／窗口与 WebView DOM 观察分别留证。硬件来源不伪填：SendInput 是 OS 按键注入，InjectTouchInput 是 OS 触控注入；OSK 是辅助功能屏幕键盘，不是 TabTip。

| 批次 | 实际结果 | 证据与范围 |
| --- | --- | --- |
| `os-input-1` | 2 失败，另有 1 个 OSK 清理错误 | 实际 IME 已进入组合；候选观察和 OSK UIA 子进程执行策略失败，旧失败保留 |
| `os-input-2` | 2 失败，无错误／跳过 | 实际拼音组合到 `ni'hao`；候选 UI 超时，OSK PrintWindow 空图失败，清理成功 |
| `os-input-3` | 1／1 通过 | 对目标窗口核实后以桌面 BitBlt 捕获真实 OSK；长草稿与 DOM 按钮状态通过，该批未点击键盘键。[摘要（原始产物已删除）](../../../README.md#已删除的材料)、[原生键盘帧（原始产物已删除）](../../../README.md#已删除的材料) |
| `os-input-4` | 1 失败，无错误／跳过 | 候选窗超时；TextInputHost cloaked 窗排除，未用隐藏窗冒充可见候选 |
| `os-ime-enter-1` | 1 失败 | 旧测试错误要求结束事件 `isTrusted=true`；实际结束事件为 false，草稿 `nihao`，当批未执行之后的无消息断言 |
| `os-ime-enter-2` | 1／1 通过 | Windows Enter 实际结束 OS 输入法组合；可信组合开始／按键、无脚本 composition 派发；保留原始结束事件 false。草稿等于结束文本 `nihao`，双 RAF 后后端消息为空、没有弹层。[摘要（原始产物已删除）](../../../README.md#已删除的材料)、[完整事件与运行时版本](../../../native-acceptance-evidence.zip)（包内：`docs/archive/2026-10-07/development/frontend-completion/ticket-23/native/os-ime-enter-2/NativePlatformAcceptance/test_real_system_ime_enter_ends_composition_without_creating_run/ime-completion-trace.json`） |
| `os-touch-1` | 1 错误 | 第一帧触控注入 WinError 87，未产生有效接触；不算产品交互失败 |
| `os-touch-2` | 1／1 通过 | 修正单指 pointer_id 为 0；实际 OS 触控菜单、主导航、关闭及长内容滚动，草稿保留。[摘要](../../../native-acceptance-evidence.zip)（包内：`docs/archive/2026-10-07/development/frontend-completion/ticket-23/native/default-download-7-final/summary.json`） |

输入法测试的预期依据[微软拼音说明](https://support.microsoft.com/en-us/windows/hardware/input-devices/microsoft-simplified-chinese-ime)：Space 选择当前中文候选，Enter 关闭候选而不选择；因此 Enter 后保留拼音不是乱码。结束事件来源不单靠 `isTrusted` 判断：[Blink 输入法实现](https://raw.githubusercontent.com/chromium/chromium/main/third_party/blink/renderer/core/editing/ime/input_method_controller.cc)的结束事件进入 `DispatchScopedEvent`，开始／更新则进入显式设置信任值的[EventTarget::DispatchEvent](https://raw.githubusercontent.com/chromium/chromium/main/third_party/blink/renderer/core/dom/events/event_target.cc)。实际 WebView Runtime `Edg/155.0.4283.39` 的 false 原值与全过程保存；没有改写属性或制造组合事件。旧失败不改记通过。

追加的 `os-keyboard-4` 与 `os-ime-space-1` 各执行 1 项、各 1 失败，0 error／skip。前者实际鼠标命中 OSK 后未收到 `a`，可信按键、发送按钮遮挡和后端为空断言未执行；后者 Space 后仍为 `nihao`，没有继续到中文正文 Enter 发送及单条消息断言。失败不覆盖此前只检查 OSK 界面存在的通过，也不覆盖 Enter 结束组合不误发送的单独通过。[本轮模型、命令、结果、日志与清理](../../../frontend-history.zip)（包内：`docs/archive/2026-10-07/development/frontend-completion/ticket-23/validation/native/os-input-final-report.md`）。已通过的触控／输入法结束检查无需重复整批回归。

自建 Win32 EDIT 对照分两次运行，均完成窗口销毁与诊断线程布局恢复，不计为产品验收：

- [输入法对照（原始产物已删除）](../../../README.md#已删除的材料)实际把 NIHAO＋Space 转成 `你好`，诊断线程只读 TSF active profile 为中文 Microsoft Pinyin。证明该线程和控件的转换可用，不能推断 Tauri 的焦点线程也相同。
- [OSK 对照](../../../native-acceptance-evidence.zip)（包内：`docs/archive/2026-10-07/development/frontend-completion/ticket-23/validation/native/input-control-1/osk.json`）点击后 EDIT 仍为空；调用者完整性 RID 8192／UIAccess 0，OSK RID 12288／UIAccess 1。结合[Windows 输入注入的完整性级别限制](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput)，当前普通测试进程没有注入更高完整性 OSK 的能力。保留 OSK 产品点键未验，不把该阻断说成产品缺陷；新建 OSK 已关闭，原 TabTip 保留。
- `os-ime-space-2-paced` 保持原产品断言，NIHAO 各键后等待 200ms，仍 **1 失败、0 error／skip**。新的[失败事件（原始产物已删除）](../../../README.md#已删除的材料)显示首个 `n` 为普通 keydown，仅 `ihao` 进入输入法组合，Space 后结束数据也是 `ihao`，草稿为 `nihao`。旧夹具把普通字母加不完整组合误当整个拼音；之后加强完整组合初始化核实，原用例复验结果见下一项，未归因为应用输入框问题。
- `os-ime-full-preedit-1` 复验原用例 **2／2 通过、0 失败／错误／跳过**，没有使用 timing wrapper。初始化必须核实全部 NIHAO 属于同一组合，最多两次，未满足则真实 Esc 结束并清空本例状态后重试，保留每次原始事件。Space 用例第一次即完整 `ni'hao`，真实选词得到 `你好`，后续普通 Enter 恰好提交一条 human `你好` 并完成；Enter 护栏用例第一次不完整、第二次完整，Enter 只结束拼音组合，消息为空。无脚本 composition 派发。[两用例结果](../../../native-acceptance-evidence.zip)（包内：`docs/archive/2026-10-07/development/frontend-completion/ticket-23/native/os-ime-full-preedit-1/cases.json`）、[Space 初始化（原始产物已删除）](../../../README.md#已删除的材料)、[Enter 初始化（原始产物已删除）](../../../README.md#已删除的材料)。

主 agent 与 Spec 轴重读定稿规格后确认：AC6／故事 114 要求软键盘／长内容／提示并存时发送、审批、取消与重连可达，以及实际 IME／触控／Esc／焦点操作；首版标准 11 还明确要求四档各自完成四种操作。没有要求辅助 OSK 点 `a` 或候选 UIA 截图。两项增强探针的失败与未取得证据仍保留，不增设为关闭硬前置；不同独立场景的成功也不代替明确的并存要求。

- `osk-coexistence-1` **1 失败**，缺少托盘错误的准备条件，停在等待提示；修正为现有 acceptance host 启动前缺图标夹具，原生 `get_tray_error` 真实返回错误，未 Mock 提示组件。
- `osk-coexistence-2` **1 失败、0 error／skip**，390×600、OSK／长草稿／TrayNotice、取消按钮真实命中、Win32 鼠标打开确认、Windows Esc 关闭、草稿和阅读锚点保持的前序断言均通过。之后已等到 `已完成`，但通用 `complete()` 辅助函数还要求 `at_latest()`，与本例已暂停跟随的阅读意图冲突；这是测试后置条件不适用，不是运行未完成。原失败和后端事实保留。[本批报告](../../../frontend-history.zip)（包内：`docs/archive/2026-10-07/development/frontend-completion/ticket-23/validation/native/osk-coexistence-2-report.md`）。
- 在既有真实 reading Agent 的审批模式上扩展并存用例，再新增四个独立尺寸用例，补发送、逐项批准／提交、GET 重连与确认取消；真实持久状态和原文另以 HTTP 核对。断流和前三次 GET 503 只在公开传输边界构造，未改产品状态。各阶段单独保存原生帧、布局与身份，结果按下列实际批次记录。
- `interaction-matrix-1` 的 1440×900 原型 **1 失败、0 error／skip**，批准选择后点击提交，再等 `已完成` 超时；旧产物没有审批 POST／点击目标记录，不能确定失败归属。后续改为浏览器滚轮输入准备滚动，等待布局稳定并核实 DOM 点击目标，再用 Win32 鼠标实际激活；增加实际请求及可信点击记录，并保证异常时释放鼠标按键。原失败不覆盖。
- `interaction-matrix-2` 的 1440×900 原型 **1 失败、0 error／skip**；审批同 Run 完成、原长草稿发送、手动重连与草稿／锚点保持均已通过。随后总请求序列断言失败：首个 Run 的两个 GET 被错误地并入第二个 Run。原始路径分别确认首 Run GET 2 次、新 Run GET 4 次、发送 POST 2 次、审批 POST 1 次，并有处理审批／批准／提交／发送／重连的可信点击。修正统计按新 `run_id` 隔离恢复读取，所有原始请求继续保存；该批没有执行后续确认取消，仍计失败。
- `interaction-matrix-3` 的 1440×900 原型 **1／1 通过、0 失败／错误／跳过**。审批同 Run 完成、原长草稿发送、手动 GET 重连、实际确认取消与持久身份均完成；每项 Windows 激活都有新增可信点击，审批与取消 POST 各 1 次，两个发送 POST、不重发原文，新 Run 恰 4 个恢复 GET。另外三档与 OSK 并存完整操作随后单独定向验收，不提前记通过。[本批结果（原始产物已删除）](../../../README.md#已删除的材料)。
- `interaction-matrix-final-1` **4 执行：1 通过、3 失败、0 error／skip**。1280×800 完成四阶段及所有持久／请求／可信点击断言。1024×768 与 390×844 的准备发送错误依赖窄屏不挂载的会话行，实际只有 GET、没有发送 POST；改为真实 composer 发送。OSK 用例尚未打开键盘，在长草稿增高后 Home 定位超时；增加 textarea／时间线三帧稳定等待再执行原 Home 断言，尚未确定原失败根因。只复验后三项，已绿的 1440／1280 不重复。[原逐项结果（原始产物已删除）](../../../README.md#已删除的材料)。
- `interaction-matrix-final-2` **3 执行：1 通过、2 失败、0 error／skip**。1024×768 完成四阶段。OSK 已审批、发送和激活重连，失败位置是恢复等待条件：窄屏隐藏 `.app-connection`，不能从 body 可见文本等待“观察已建立”；事后 DOM 有该状态且恢复提示已消失，仍不能倒算超时断言通过，后续取消也未执行。改为 accepted DOM 状态、可见提示消失，再用真实 GET 核对 `running`，保留消息、草稿和锚点断言。390×844 在批准选择前的 `WindowFromPoint` 归属保护失败，没有点击其他窗口。只读后验发现该 HWND 属于左侧 `Shell_TrayWnd`；原失败时没有记录点位／窗口框，不能仅凭后验归因为产品。新增每次点击目标元数据及前景核实，同一 DPI-aware 测试坐标下把验收拥有的窄屏窗口移入 monitor Work 区，保持实际 CSS 尺寸及完整原生窗口框检查，不修改任务栏或用户应用。[本批结果（原始产物已删除）](../../../README.md#已删除的材料)、[原始命令及源码哈希（原始产物已删除）](../../../README.md#已删除的材料)。
- `interaction-matrix-final-3` **2／2 功能通过、0 失败／错误／跳过**：390×844 与 OSK／长内容／长草稿／真实 TrayNotice 的 390×600 场景均完成审批、原文发送、有限 GET 后手动重连及确认取消；各阶段 DPR 1.5。主 agent 独立核对 390 原生审批／取消帧与后端事实。但本批初开 OSK 的 `osk-coexistence-native.png` 实际捕获了背景浏览器页面，**该图无效，不能证明 OSK 可见画面**；虽 `IsWindowVisible` 和九点 HWND 归属断言通过，也不能以元数据替代图像内容。两项功能 pass 保留，截图另补证；旧图留作失效证据，不作为键盘截图展示。OSK 捕获移动到四阶段之后，只读自身 UIA、等待 DWM 组合后仍核实原 HWND／九点和框，保留所有操作断言；另起 `final-4` 仅复验这一受影响例。[本批结果（原始产物已删除）](../../../README.md#已删除的材料)、[四阶段原始记录（原始产物已删除）](../../../README.md#已删除的材料)。
- `interaction-matrix-final-4` **1／1 通过、0 失败／错误／跳过**，只复验 OSK 例。完整四阶段再次通过；主 agent 和测试子 agent 实际查看新图，明确可见“屏幕键盘”标题与完整键位，取证有效。键盘图与 Tauri 窗口帧分张留证，不描述为一张同屏截图。原背景图不改写为通过。[本批结果（原始产物已删除）](../../../README.md#已删除的材料)、[完整事实](../../../native-acceptance-evidence.zip)（包内：`docs/archive/2026-10-07/development/frontend-completion/ticket-23/native/interaction-matrix-final-4/NativePlatformAcceptance/test_osk_long_draft_tray_notice_and_native_cancel_remain_reachable/result.json`）、[真实键盘图](../../../native-acceptance-evidence.zip)（包内：`docs/archive/2026-10-07/evidence/4d84a7a3eec8ecf9-osk-coexistence-native.png`）。

末批使用 `gpt-6-luna / max`；主 agent 已核对[实际命令及退出码（原始产物已删除）](../../../README.md#已删除的材料)、[原始日志（原始产物已删除）](../../../README.md#已删除的材料)、[源文件末尾哈希（原始产物已删除）](../../../README.md#已删除的材料)与[清理观察](../../../native-acceptance-evidence.zip)（包内：`docs/archive/2026-10-07/development/frontend-completion/ticket-23/validation/native/interaction-matrix-final-4/post-batch-cleanup-observation.json`）。执行前后平台源码 SHA-256 `965AB30E612AC5E5E880460B5334B66EAD37210E91D77C3B4453874998274E62` 一致；runner 源码也一致。final-3／4 自有 Tauri、OSK 及后端已退出，9238／45200 空闲，无新临时目录，原 5173／TabTip 保留。默认下载第 7 批受工具限制遗留的临时目录仍按下节记录。

最后 **五个唯一原生完整操作场景**分批各有通过证据；不把重复 OSK 例累计，也不声明一次五例全绿。主 agent 按原始 JSON 核对每个场景的四阶段 CSS 尺寸、实际身份、可信点击、两条 human、30 行原文与下一条草稿、首 Run completed／第二 Run cancelled，以及两个发送 POST／一个审批 POST／一个取消 POST、第二 Run 三次自动加一次手动 GET。身份及结果文件哈希见[派生事实核对](../../../native-acceptance-evidence.zip)（包内：`docs/archive/2026-10-07/development/frontend-completion/ticket-23/validation/native/workflow-matrix-audit.json`），该文件是保存结果的核对，未另执行测试。

| 场景 CSS 内容区 | 最终通过批次 | 四阶段实际 DPR |
| --- | --- | --- |
| 1440×900 | `interaction-matrix-3` | 2 |
| 1280×800 | `interaction-matrix-final-1` | 2 |
| 1024×768 | `interaction-matrix-final-2` | 2 |
| 390×844 | `interaction-matrix-final-3` | 1.5 |
| OSK／长内容／长草稿／TrayNotice，390×600 | `interaction-matrix-final-4` | 1.5 |

## 默认下载诊断与覆盖边界

- 历史第 1 批真实 WebView 导出未调用 `Browser.setDownloadBehavior`，取得 69,777 字节 UTF-8 Markdown；完整历史、工具参数／结果／artifact 与未知字段断言通过，消息与草稿不变。退出即时断言通过，但最终后验原下载目录为空，不能声明该批持久保存成功。[实际文件归档](../../../backend-history.zip)（包内：`docs/archive/2026-10-07/evidence/8da5ba861d2a1cd8-observed-default-export.md`）、[身份及哈希（原始产物已删除）](../../../README.md#已删除的材料)。后面的第 6／7 批才有完成及退出后留存证据。没有把自动下载说成用户选择路径／点击取消。
- 默认保存 UI 取消：旧 SaveAs 探针没有找到预期窗口，失败保留；该批 JSON 虽记录文件名，后验目录为空，不能倒推旧批字节已验证。另有 CDP 下载 GUID 取消通过，范围独立。[旧批文件后验检查（原始产物已删除）](../../../README.md#已删除的材料)。规格按实际 UI 验收，不强制某一种 SaveAs 形态。
- `default-download-2／3／4` 各执行 1 项、各 1 失败，均在完整字节核对后、宿主退出与 `stop_hosts()` 后源文件不存在。第 4 批缩短完整路径到 184 个字符，文件名完整，仍丢失；长路径猜测未获支持。69,777 字节归档副本 SHA-256 `6563f2bfdd43154fc1a71b8ed7f8e9b3d5f7e3d2e8f05f4ba77fc19fd9503fdb` 仅证明读取内容，不证明持久保存。[失败（原始产物已删除）](../../../README.md#已删除的材料)、[退出后核对（原始产物已删除）](../../../README.md#已删除的材料)。
- 隔离 profile History 的 downloads 表为空；仅有验收拥有的 Tauri／WebView 可见窗口，UIA 中下载面板边界无效，没有 SaveAs 或可操作取消控件。UIA 深度限制保留，不将未观察到控件说成系统绝无该控件。本地 Wry 默认下载 handler 设置 `Handled=true`，这与隐藏默认 UI 一致；未改变产品下载策略。
- `default-download-5` 1 失败：被动 Page 下载事件的 6 条记录始终为 `inProgress`，即使 `receivedBytes=totalBytes=69,777`，30 秒内仍无终态，退出后文件消失。字节齐全不等于完成；旧 SaveAs 夹具强制 `prompt_for_download=true`。[真实结果（原始产物已删除）](../../../README.md#已删除的材料)。
- `default-download-6-default-pref` 单变量对照 1／1 通过：只移除本例隔离 profile 的强制询问偏好，保留隔离目录；没有修改产品或下载协议策略。同 GUID 的 8 条事件最后为 `completed`，退出后原文件仍为 69,777 字节，SHA-256 `4aea9d255dc01005208e4762fa7c9bf8c88b235b8811183e83a43b45bb37c60a` 与观察副本一致。[完整对照证据](../../../frontend-history.zip)（包内：`docs/archive/2026-10-07/development/frontend-completion/ticket-23/validation/native/os-input-final-report.md#默认下载偏好对照通过`）。旧 wrapper 原字节归档于 [历史诊断代码](../../../frontend-history.zip)（包内：`docs/archive/2026-10-07/development/frontend-completion/ticket-23/debug/README.md`），不适用于修正后的当前夹具。
- 默认夹具现已省略该非默认偏好，仅旧 SaveAs 探针仍保留强制询问设置；被动观察器只核对同一个下载 GUID。`default-download-7-final` 不经 wrapper 复验原用例 **1／1 通过、0 失败／错误／跳过**：默认偏好、真实 `completed`、完整工具记录、草稿与历史不变、宿主退出后原文件留存均通过。[原用例结果](../../../native-acceptance-evidence.zip)（包内：`docs/archive/2026-10-07/development/frontend-completion/ticket-23/native/default-download-7-final/summary.json`）。前五批仍保留失败／后验缺失，不能倒推其已通过。
- 第 7 批拥有的宿主／后端／runner 均退出，端口释放，原 5173 与 TabTip 保留。隔离 profile 临时目录 `C:\Users\Orcs0\AppData\Local\Temp\shikigen native acceptance hcx83pmj` 仍在；清理命令被工具启动层以 `blocked by policy` 拒绝，PowerShell 未启动、未删除文件，不是自动审批拒绝。[清理记录](../../../native-acceptance-evidence.zip)（包内：`docs/archive/2026-10-07/development/frontend-completion/ticket-23/validation/native/default-download-7-final/temp-fixture-cleanup.json`）。下载正文在证据目录留存，源／副本 SHA-256 为 `5a9c4e3dfb61c92bdeb246d517e452b2b4859fc81fed66622ac47e943650d270`。派生证据把 runner PID 29148 误写为退出码；实际 [runner-result（原始产物已删除）](../../../README.md#已删除的材料) 退出 0，并有独立[字段更正说明（原始产物已删除）](../../../README.md#已删除的材料)，未覆盖原文件。
- 实体键盘／滚轮和手指硬件触控、TabTip 触摸键盘未执行；OS 注入结果不能证明特定硬件。规格要求实际 OS 操作，不额外强制必须由人操作；未验硬件作为覆盖限制记录。
- [原生操作与硬件边界](manual-acceptance.md)记录 agent 已取得及正在补齐的结果，替换此前额外设为前置的“本人操作”清单。没有将未收到的人工结果填写为通过。

## 覆盖映射与审查

[覆盖审计](coverage.md)逐项映射原首版 17 条与 116 条用户故事，区分本轮联合结果、既有逐票证据、真实模型与夹具范围；它不是 116 条都已完成的声明。

审查固定于本轮开始保存的 264 文件快照，不使用 Git：[实际差异（原始产物已删除）](../../../README.md#已删除的材料)、[变化文件（原始产物已删除）](../../../README.md#已删除的材料)。[Standards 审查](../../../frontend-history.zip)（包内：`docs/archive/2026-10-07/development/frontend-completion/ticket-23/standards-review.md`）与 [Spec 审查](../../../frontend-history.zip)（包内：`docs/archive/2026-10-07/development/frontend-completion/ticket-23/spec-review.md`）分别复核；`is_list_only` 与 `read_owned_process_tree` 命名已修正，最后原生夹具变化也已定向复核。规范问题与需求缺口不相互抵消。Standards 无剩余硬性违规，五项判断性观察保留；Spec 的窄屏操作与 OSK 图像缺口已有真实通过证据，不将未执行的硬件或增强探针作为通过结果。

## 第 23 票验收状态

| AC | 当前结论 |
| --- | --- |
| 1．17 条与 116 故事逐项记录 | 已完成逐项映射和范围审计；复用分票与本轮实际证据，增强边界和历史失败明确保留，不等于 116 故事在一次联合批次全部重跑通过 |
| 2．真实模型任务与运行生命周期 | 五条唯一在线路径通过；竞争另有离线证据，生产宿主归属分别取证 |
| 3．竞态与持久事实 | 完整回归及原生修复后相关专项通过；最新 ChatReading、分页及 Windows 输入等定向回归通过 |
| 4．资源、系统打开、完整复制／导出 | 系统派发、完整系统复制通过；默认下载原用例完成并在宿主退出后留存，历史非默认 SaveAs 探针失败独立保留，实际下载 GUID 取消已有证据 |
| 5．原稿与四档原生窗口 | 实测 CSS／DPI、完整窗口帧与响应式路径通过；四档各自完整发送／审批／重连／取消均有实际通过，所属构建和缩放分别记录 |
| 6．长内容、焦点、IME、触控／软键盘 | Windows 输入／剪贴板、真实 IME Space 选词与单次发送／Enter 护栏、OS 触控通过；OSK／长内容／增高草稿／TrayNotice 并存完整四操作通过，补拍的真实键盘图经主 agent 实际查看有效。增强点键失败和硬件边界单列 |
| 7．托管、单实例、托盘与动态地址 | 生产 `final-2` 通过，新增托盘显示入口已核对 |
| 8．联合证据与发现归属 | 本报告串联分票、完整回归与联合续验，产品缺陷已修正，历史失败、增强未验与清理限制保留；未改变产品规则或重开父地图 |

主 agent 已逐项核对原始日志、请求、持久消息／Run、身份、源码哈希及实际图像后关闭本票。可自动化的 Windows 检查由 agent 执行；实体硬件、TabTip 与未通过增强探针保持未验，不用脚本替填人的结果。测试进程／端口清理完成，一个受工具限制的隔离临时目录保留。未执行任何 Git 命令。
