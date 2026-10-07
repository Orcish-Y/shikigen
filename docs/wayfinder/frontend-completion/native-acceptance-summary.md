# 首版 Tauri 原生验收汇总与未覆盖范围

日期：2026-10-07。

来源：[原生操作清单](../../archive/2026-10-07/development/frontend-completion/ticket-23/manual-acceptance.md)、[第 23 票联合报告](../../archive/2026-10-07/development/frontend-completion/ticket-23/report.md)。本页汇总已有结果，没有新增测试执行。

## 结论

原生操作清单已逐项复核。已取得 Windows／Tauri 实际操作、输入法、窗口、消息与下载证据；仍有实体外设、TabTip、候选窗口画面、OSK 按键输入和保存弹窗取消等未覆盖项。

[第 23 票](implementation/23-native-workflow-acceptance.md)的八项约定验收已满足并关闭，[实施索引](implementation/index.md)中的 23 张票据均已验收。未执行或未成功的增强检查继续保留，不记为通过。

最终执行验证的子 agent 使用 **`gpt-6-luna / max`**；主 agent 核对原始日志、JSON、身份、图像与清理记录。Windows 按键／触控注入证明实际 OS 操作路径，实体设备的驱动与操作体验仍需单独验证。

## 已验证结果

| 检查 | 已确认的结果 | 操作方式与证据 |
| --- | --- | --- |
| 原文输入、快捷键与焦点 | 原文及换行保留；Enter、全局面板保护和相关阅读／焦点路径通过 | Windows `SendInput`；[原生续验收报告](../../archive/2026-10-07/frontend-history.zip)（包内：`docs/archive/2026-10-07/development/frontend-completion/ticket-23/validation/native/resume-report.md`） |
| 输入法结束组合 | 输入拼音后按 Enter 结束组合，保留拼音，不新增消息或弹层 | 实际已安装的 Windows IME；[原始事件](../../archive/2026-10-07/native-acceptance-evidence.zip)（包内：`docs/archive/2026-10-07/development/frontend-completion/ticket-23/native/os-ime-enter-2/NativePlatformAcceptance/test_real_system_ime_enter_ends_composition_without_creating_run/ime-completion-trace.json`） |
| 中文选词后发送 | Space 选择“你好”，随后普通 Enter 恰好提交一条消息；组合期间 Enter 不误发送 | 两个原用例均通过；[逐项结果](../../archive/2026-10-07/native-acceptance-evidence.zip)（包内：`docs/archive/2026-10-07/development/frontend-completion/ticket-23/native/os-ime-full-preedit-1/cases.json`） |
| 触控菜单与滚动 | 手机菜单、主导航切换、关闭及长内容滚动通过，草稿保留 | Windows `InjectTouchInput`；[批次结果](../../archive/2026-10-07/native-acceptance-evidence.zip)（包内：`docs/archive/2026-10-07/development/frontend-completion/ticket-23/native/default-download-7-final/summary.json`） |
| 四档窗口完整操作 | 1440×900、1280×800、1024×768、390×844 实际 CSS 内容区分别完成发送、审批、GET 重连、确认取消 | 五个唯一场景审计中的四个尺寸场景；[原始事实核对](../../archive/2026-10-07/native-acceptance-evidence.zip)（包内：`docs/archive/2026-10-07/development/frontend-completion/ticket-23/validation/native/workflow-matrix-audit.json`） |
| 屏幕键盘、长草稿与提示并存 | 390×600，OSK、长内容、增高草稿与真实托盘错误提示并存；审批、发送、GET 重连、确认取消、Esc 及阅读锚点通过 | `interaction-matrix-final-4` 单例通过；[实际结果](../../archive/2026-10-07/native-acceptance-evidence.zip)（包内：`docs/archive/2026-10-07/development/frontend-completion/ticket-23/native/interaction-matrix-final-4/NativePlatformAcceptance/test_osk_long_draft_tray_notice_and_native_cancel_remain_reachable/result.json`） |
| 默认下载保存 | 下载进入 `completed`，取得完整 69,777 字节 Markdown，宿主退出后实际源文件仍保留；历史及草稿不变 | 修正夹具非默认询问偏好后，第 7 批原用例通过；[批次结果](../../archive/2026-10-07/native-acceptance-evidence.zip)（包内：`docs/archive/2026-10-07/development/frontend-completion/ticket-23/native/default-download-7-final/summary.json`） |
| 下载取消与错误边界 | 下载 GUID 取消、拒绝下载和失败边界通过，会话及草稿保持 | CDP 下载边界；具体范围见[联合报告](../../archive/2026-10-07/development/frontend-completion/ticket-23/report.md#默认下载诊断与覆盖边界)，未覆盖保存弹窗里的取消操作 |

四档尺寸及 OSK 共五个唯一完整操作场景分批各有通过证据，存在重复执行，不累计为一次五例全绿。

## 未通过或未执行项

| 项目 | 当前状态 | 已有观察与后续补测范围 |
| --- | --- | --- |
| 实体键盘与滚轮 | 未执行 | 当前证据来自 OS 注入；还需实际设备核对按键、快捷键、滚轮与焦点体验 |
| 手指触摸屏 | 未执行 | 已有 OS 触控注入证据；实体触屏的菜单、滚动与输入体验未验证 |
| TabTip 触摸键盘 | 未执行 | OSK 是辅助功能屏幕键盘；原 TabTip 进程存在不能作为输入通过证据 |
| 输入法候选窗口画面 | 未取得可见窗口证据 | `os-input-1／2／4` 探针超时，失败保留；实际选词与发送已有通过，候选 UI 画面仍需补证 |
| OSK 点击按键输入 | 增强探针未成功 | 普通测试进程与 OSK 的完整性／UIAccess 差异已记录，当前未证明键盘按键输入成功；[系统文本框与令牌对照](../../archive/2026-10-07/native-acceptance-evidence.zip)（包内：`docs/archive/2026-10-07/development/frontend-completion/ticket-23/validation/native/input-control-1/osk.json`） |
| 保存弹窗的取消操作 | 未验证 | 旧 SaveAs 探针未找到预期窗口；当前默认下载路径没有观察到可操作取消 UI。CDP 下载取消结果不能代替该 UI 操作 |

本轮没有取得人的实体操作结果。以上项目没有补填为通过，也没有据此确认产品缺陷；后续补测应分别记录实际设备、入口、操作步骤、结果和证据。

## 图像、历史与清理说明

- `interaction-matrix-final-3` 的早期 OSK 截图误拍背景浏览器页面，已标为无效；该批功能结果保留，不能用这张图证明键盘画面。
- `interaction-matrix-final-4` 补拍的[真实 OSK 图](../../archive/2026-10-07/native-acceptance-evidence.zip)（包内：`docs/archive/2026-10-07/evidence/4d84a7a3eec8ecf9-osk-coexistence-native.png`）已由主 agent 和测试子 agent 实际查看。键盘与[应用窗口图](../../archive/2026-10-07/native-acceptance-evidence.zip)（包内：`docs/archive/2026-10-07/evidence/48a0992c3fac1e75-osk-coexistence-app-native.png`）分张取证。
- 历史 IME、OSK 和下载失败按原批次保留，后续通过不覆盖旧失败记录。
- 末批自有 Tauri、后端和 OSK 已退出，测试端口释放，原 5173 服务与 TabTip 保留，见[清理观察](../../archive/2026-10-07/native-acceptance-evidence.zip)（包内：`docs/archive/2026-10-07/development/frontend-completion/ticket-23/validation/native/interaction-matrix-final-4/post-batch-cleanup-observation.json`）。
- 默认下载第 7 批的隔离临时目录 `C:\Users\Orcs0\AppData\Local\Temp\shikigen native acceptance hcx83pmj` 因工具启动层拒绝清理仍保留，见[清理限制记录](../../archive/2026-10-07/native-acceptance-evidence.zip)（包内：`docs/archive/2026-10-07/development/frontend-completion/ticket-23/validation/native/default-download-7-final/temp-fixture-cleanup.json`）。

## 详细资料

- [原生操作清单与硬件边界](../../archive/2026-10-07/development/frontend-completion/ticket-23/manual-acceptance.md)
- [完整联合验收报告](../../archive/2026-10-07/development/frontend-completion/ticket-23/report.md)
- [17 条标准与 116 条用户故事覆盖映射](../../archive/2026-10-07/development/frontend-completion/ticket-23/coverage.md)
- [Standards 审查](../../archive/2026-10-07/frontend-history.zip)（包内：`docs/archive/2026-10-07/development/frontend-completion/ticket-23/standards-review.md`）与 [Spec 审查](../../archive/2026-10-07/frontend-history.zip)（包内：`docs/archive/2026-10-07/development/frontend-completion/ticket-23/spec-review.md`）

本页为现有结果的汇总，不改变票据验收范围或状态。
