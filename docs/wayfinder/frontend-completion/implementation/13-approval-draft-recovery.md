# 恢复审批草稿并核实未知提交

Status: done

实施进度：已验收

来源：[统一实施规格](../../../../.scratch/frontend-completion/PRD.md)；[公共要求与依赖总览](index.md)。

**What to build:** 切换或重开后先核实当前请求，再恢复同一审批的选择与原因；失败或未知提交可以核实后人工继续。

**Why:** 保留用户尚未提交的工作，同时避免把旧请求或未知结果当成可直接再次执行的审批。

**API／边界：**本地审批身份／内容／版本记录；全量 GET stream、checkpoint／Interrupt；结构化审批错误及有限恢复协调。

**Blocked by:** [隐藏暂停读取并轮询会话状态](06-visibility-polling.md)；[逐项审批并继续同一运行](12-approval-resume.md)。

## 验收条件

- [x] 跨重启保存 Run、checkpoint 完整坐标、Interrupt ID／namespace、动作位置／名称／args／description／review_configs 和选择／原因，独立于 Workspace。
- [x] 先只读核实，当前仍 interrupted 且正常全量回放结束，身份内容全一致才恢复；对象键顺序不影响等价，数组顺序保留，新 checkpoint／动作默认未选择，绝不自动提交。
- [x] 旧 pending 重开转待核实；隐藏、切换、租约失效只停请求，不撤回服务端决策，保留提交内容；存储失败回退内存，会话／Run 404 只读保留核对。
- [x] 409 重建，422 保留实际校验信息，503 遵守 Retry-After，接受前网络／500／解析／中止显示未知；接受后断流只 GET 恢复，不开放旧决策。
- [x] 已 resolved 显示实际 decisions，已 invalidated／终态锁定，新请求重新选择；同一请求仍有效可人工重新提交并说明先前结果未确认，一次 GET 不保证旧请求不会稍后生效。
- [x] 只清匹配已处理／失效草稿，不清新请求；GET 失败仍保留只读选择，取消核实与审批恢复资格分开。
- [x] 公开请求、重启及迟到竞态验证内容指纹、旧响应过滤、再提交 409、未提交选择不进入历史、无自动审批和失败后可恢复。

## Comments

2026-10-06：按用户授权实施本票，明确不执行 Git 修改。新增应用级审批草稿与捕获提交记录；沿用全量 GET、有限恢复和同 Run 写互斥；本地输入只读核对，公开接口与原稿样式保持既有契约。最终验证交接见[第 13 票上下文](../../../../.scratch/frontend-completion/ticket-13/validation-context.md)，验收结果待轻量测试子 agent 核实。

2026-10-06：已完成七条验收。显式 `gpt-6-luna / max` 验证：唯一完整前端回归 164 通过；之后身份清理修复及新增用例的最终受影响专项 91 通过（含全部 13 项恢复测试）；分批 7 个唯一真实 Tauri 用例各有最终通过证据，真实 HTTP／SQLite／Graph 专项 1 通过；TypeScript、最终构建及 6 个 Python 文件 Ruff 通过，38 个 dist 文件与预置服务字节一致。原生早期夹具失败及范围边界完整保留，不改算通过；Standards／Spec 无剩余硬问题。主 agent 已核对原始日志、请求、结果和窗口截图，详见[第 13 票报告](../../../../.scratch/frontend-completion/ticket-13/report.md)。未暂存、未提交、未切换分支；物理输入／IME 和多尺寸联合验收仍归第 23 票。
