> 归档于 2026-10-07；正文状态与命令属于原开发阶段。当前完成情况见 [开发交接](../development-handoff.md)。相对路径链接已迁移；代码块中的旧 scratch 路径需按归档路径调整。

# 原生合成 IME 后 Enter 未发送

Status: needs-triage

发现于第 11 票最终验证；2026-10-05。正式旧用例：`message_drafts_acceptance.MessageDraftAcceptance.test_original_enter_composition_and_draft_survive_native_restart`，断言位置 `frontend/src-tauri/tests/message_drafts_acceptance.py:105`。

## 实际失败

原生单 runner 顺序执行 24 项；22 通过、2 失败、0 错误／跳过，exit 1。运行 UTC 14:04:44.159–14:09:11.499。另一个失败为新第 11 票纵滚夹具，单独处理。

本用例在 CDP 合成输入后发普通 Enter，等待 `len(self.users(ready, thread)) == 1` 达 30 秒超时。现场输入框有焦点和原文草稿，`__sends=[]`，公开历史 `data=[]`；没有 POST，不能归因于后端拒收。失败现场没有捕获键盘／composition 事件和按下 Enter 时的发送资格，因此不能确定是哪一个客户端拦截条件。

- [首轮日志与命令元数据](../archive/2026-10-07/unresolved-issues-evidence.zip)（包内：`docs/archive/2026-10-07/development/frontend-completion/ticket-11/logs/native-all.meta.json`）
- [正式错误日志](../archive/2026-10-07/unresolved-issues-evidence.zip)（包内：`docs/archive/2026-10-07/development/frontend-completion/ticket-11/logs/native-all.stderr.log`）
- [失败现场](../archive/2026-10-07/unresolved-issues-evidence.zip)（包内：`docs/archive/2026-10-07/development/frontend-completion/ticket-11/native/04-message-drafts/test_original_enter_composition_and_draft_survive_native_restart/failure-evidence.json`）
- [DOM](../archive/2026-10-07/unresolved-issues-evidence.zip)（包内：`docs/archive/2026-10-07/development/frontend-completion/ticket-11/native/04-message-drafts/test_original_enter_composition_and_draft_survive_native_restart/failure-dom.html`）
- [截图](../archive/2026-10-07/unresolved-issues-evidence.zip)（包内：`docs/archive/2026-10-07/development/frontend-completion/ticket-11/native/04-message-drafts/test_original_enter_composition_and_draft_survive_native_restart/window.png`）

## 正式隔离诊断

显式 `gpt-6-luna / max` 执行原样旧用例；只安装只读事件监听与记录 Input 命令，不人工发 compositionend，不改变按键／等待／断言。隔离 1 项通过，unittest 14.836 秒，exit 0；不抵消首轮失败。

原文候选 Enter：`trusted=false,keyCode=229,isComposing=true`，未发送。随后 `Input.insertText` 后出现 `compositionend`（trusted=false，timeStamp 89.899ms）；普通可信 Enter（timeStamp 178.700ms）`isComposing=false,keyCode=13,repeat=false`，距 compositionend 约 88.8ms，大于现有保护窗口 50ms。按下时 textarea 聚焦、非空草稿、发送按钮可用，随后正确发送并重启保留原文与草稿。

- [诊断脚本](../archive/2026-10-07/unresolved-issues-evidence.zip)（包内：`docs/archive/2026-10-07/development/frontend-completion/ticket-11/ime-diagnostic.py`）
- [事件轨迹](../archive/2026-10-07/unresolved-issues-evidence.zip)（包内：`docs/archive/2026-10-07/development/frontend-completion/ticket-11/ime-diagnostic/04-ime/test_original_enter_composition_and_draft_survive_native_restart/ime-events.json`）
- [成功用例记录](../archive/2026-10-07/unresolved-issues-evidence.zip)（包内：`docs/archive/2026-10-07/development/frontend-completion/ticket-11/ime-diagnostic/04-ime/test_original_enter_composition_and_draft_survive_native_restart/result.json`）
- [隔离日志](../archive/2026-10-07/unresolved-issues-evidence.zip)（包内：`docs/archive/2026-10-07/development/frontend-completion/ticket-11/logs/native-ime-diagnostic.stderr.log`）

重现命令（repo 根目录；先构建 frontend/dist；9238/45200 独占，5173 只复用匹配 dist 的服务）：

```powershell
$env:PYTHONPATH = 'C:\code\shikigen-agent\tests;C:\code\shikigen-agent\frontend\src-tauri\tests;C:\code\shikigen-agent\packages\harness'
.venv/Scripts/python.exe -X utf8 .scratch/frontend-completion/ticket-11/ime-diagnostic.py
```

## 下一步

在完整原生顺序里保留事件轨迹，核对 Enter 当刻的 composition、repeat、时间戳、draft 与发送资格；需要先复现首轮现象，再决定修产品或修夹具。当前根因、与本票的关系及稳定性均未确认，不称作环境问题或已修复。没有修改输入产品代码或旧测试断言。物理键盘／系统候选面板仍属于第 23 票的覆盖。
