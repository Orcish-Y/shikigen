> 归档于 2026-10-07；正文状态与命令属于原开发阶段。当前完成情况见 [开发交接](../../../../../development-handoff.md)。相对路径链接已迁移；代码块中的旧 scratch 路径需按归档路径调整。

# 第 23 票：原生操作证据与硬件覆盖边界

依据：[联合验收票](../../../../../wayfinder/frontend-completion/implementation/23-native-workflow-acceptance.md)及[统一规格](../PRD.md#实机证据与完成标准)。规格要求真实 Windows／Tauri 操作证据。此前本页将人的实体输入设为额外前置，用户要求由 agent 自行继续，现按实际操作方式与覆盖范围记录；未执行的硬件检查仍不算通过。

所有原生前景检查串行执行，隔离后端、窗口与草稿；保存实际入口、命令、日志、截图和身份，不修改用户配置或 Git。

## 已取得的证据

| 检查 | 实际结果与方式 | 证据／剩余范围 |
| --- | --- | --- |
| 原文输入、快捷键和焦点 | `final-5` Windows SendInput 原文／换行／Enter／全局面板保护通过；`final-4` 阅读及焦点相关定向通过 | [续验收报告](../../../frontend-history.zip)（包内：`docs/archive/2026-10-07/development/frontend-completion/ticket-23/validation/native/resume-report.md`）。由 OS 注入真实按键，未声称人的实体键盘或滚轮 |
| 系统中文输入法结束组合 | `os-ime-enter-2` 1／1 通过；实际已安装输入法处理拼音，Windows Enter 结束组合、保留 `nihao`，没有新增消息或弹层 | [原始事件](../../../native-acceptance-evidence.zip)（包内：`docs/archive/2026-10-07/development/frontend-completion/ticket-23/native/os-ime-enter-2/NativePlatformAcceptance/test_real_system_ime_enter_ends_composition_without_creating_run/ime-completion-trace.json`）。微软拼音 Enter 不选择中文候选，Space 选中；结束事件的原始 `isTrusted=false` 保留，来源以可信开始／按键及无 JS composition 派发核对 |
| 中文候选选中后显式发送 | `os-ime-full-preedit-1` 两原用例 2／2 通过；真实 Space 得到 `你好` 后显式 Enter 只发送一次，另一用例候选 Enter 不发消息 | [逐项结果](../../../native-acceptance-evidence.zip)（包内：`docs/archive/2026-10-07/development/frontend-completion/ticket-23/native/os-ime-full-preedit-1/cases.json`）。旧 Space 失败保留；夹具修正为核实整个 preedit，不把普通字母加残缺组合误判为完整拼音 |
| 输入法候选窗口 | 真实组合事件到达；`os-input-1／2／4` 未观察到可见候选窗，超时失败保留 | 不用 cloaked TextInputHost 窗口或合成 DOM 冒充候选 UI 截图；候选 UI 可见性仍待核实 |
| 触控菜单与滚动 | `os-touch-2` 1／1 通过；Windows InjectTouchInput 完成手机菜单、主导航切换、关闭及长内容滚动，草稿保留 | [触控批次](../../../native-acceptance-evidence.zip)（包内：`docs/archive/2026-10-07/development/frontend-completion/ticket-23/native/default-download-7-final/summary.json`）。真实 OS 触控注入及可信 DOM 触控事件，未声称实体手指或触屏硬件已验 |
| 四档完整操作 | 1440×900、1280×800、1024×768、390×844 四个唯一场景分批各通过发送、审批、GET 重连及确认取消，核对真实身份、原文、草稿与后端事实 | [原始结果核对](../../../native-acceptance-evidence.zip)（包内：`docs/archive/2026-10-07/development/frontend-completion/ticket-23/validation/native/workflow-matrix-audit.json`）。实际 CSS 尺寸、DPR、原生帧及可信 Windows 点击分别记载；未把不同批次累计成一次全绿 |
| 屏幕键盘、长草稿和提示并存 | `interaction-matrix-final-4` 1／1 通过：390×600，真实 OSK 与长内容、增高草稿、TrayNotice 并存，审批、发送、GET 重连、确认取消、Esc 与阅读锚点均核对 | [实际结果](../../../native-acceptance-evidence.zip)（包内：`docs/archive/2026-10-07/development/frontend-completion/ticket-23/native/interaction-matrix-final-4/NativePlatformAcceptance/test_osk_long_draft_tray_notice_and_native_cancel_remain_reachable/result.json`）、[真实键盘图](../../../native-acceptance-evidence.zip)（包内：`docs/archive/2026-10-07/evidence/4d84a7a3eec8ecf9-osk-coexistence-native.png`）。主 agent 实际查看此图；final-3 初开截图误拍背景，已标为无效。增强 OSK 点键仍失败，见[令牌对照](../../../native-acceptance-evidence.zip)（包内：`docs/archive/2026-10-07/development/frontend-completion/ticket-23/validation/native/input-control-1/osk.json`），未新增为规格门槛 |
| 默认下载保存 | 第 6 批只移除旧夹具的非默认询问偏好后 1／1 通过；修正后第 7 批原用例 1／1 通过 | [第 7 批结果](../../../native-acceptance-evidence.zip)（包内：`docs/archive/2026-10-07/development/frontend-completion/ticket-23/native/default-download-7-final/summary.json`）：同 GUID `completed`、完整 69,777 字节、宿主退出后实际源文件留存。前五批失效／失败保留；不把下载保存说成 SaveAs UI 取消 |
| 下载取消／错误 | 既有真实 WebView 下载 GUID 取消、deny 及失败边界通过，会话和草稿保持 | CDP 下载边界与原生取消 UI 分别记录；默认 Wry 隐藏下载界面，不强制假设 SaveAs 形态，尚未找到可操作取消 UI |

## 未声称完成的硬件范围

- 人用实体键盘／滚轮输入，以及手指触摸屏均未执行。Windows 注入结果不能证明特定外设的驱动、布局与触控体验。
- OSK 是 Windows 辅助功能屏幕键盘；不是 `TabTip` 触摸键盘。原有 TabTip PID `14204` 保留，没有把它的进程存在算作输入通过。
- 旧“本人操作”六项均未收到人的结果。本页列出的新增证据均由 agent 执行，不替人填写验收。

这些限制与已完成的 OS 自动化分开报告。可自动化的验收已由 agent 执行并保存证据，主 agent 核对八项验收后关闭第 23 票；未执行的实体外设和增强探针保持未验，不倒算为通过。
