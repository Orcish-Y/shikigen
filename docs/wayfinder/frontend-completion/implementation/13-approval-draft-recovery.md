# 恢复审批草稿并核实未知提交

Status: ready-for-agent

实施进度：待实施

来源：[统一实施规格](../../../../.scratch/frontend-completion/PRD.md)；[公共要求与依赖总览](index.md)。

**What to build:** 切换或重开后先核实当前请求，再恢复同一审批的选择与原因；失败或未知提交可以核实后人工继续。

**Why:** 保留用户尚未提交的工作，同时避免把旧请求或未知结果当成可直接再次执行的审批。

**API／边界：**本地审批身份／内容／版本记录；全量 GET stream、checkpoint／Interrupt；结构化审批错误及有限恢复协调。

**Blocked by:** [隐藏暂停读取并轮询会话状态](06-visibility-polling.md)；[逐项审批并继续同一运行](12-approval-resume.md)。

## 验收条件

- [ ] 跨重启保存 Run、checkpoint 完整坐标、Interrupt ID／namespace、动作位置／名称／args／description／review_configs 和选择／原因，独立于 Workspace。
- [ ] 先只读核实，当前仍 interrupted 且正常全量回放结束，身份内容全一致才恢复；对象键顺序不影响等价，数组顺序保留，新 checkpoint／动作默认未选择，绝不自动提交。
- [ ] 旧 pending 重开转待核实；隐藏、切换、租约失效只停请求，不撤回服务端决策，保留提交内容；存储失败回退内存，会话／Run 404 只读保留核对。
- [ ] 409 重建，422 保留实际校验信息，503 遵守 Retry-After，接受前网络／500／解析／中止显示未知；接受后断流只 GET 恢复，不开放旧决策。
- [ ] 已 resolved 显示实际 decisions，已 invalidated／终态锁定，新请求重新选择；同一请求仍有效可人工重新提交并说明先前结果未确认，一次 GET 不保证旧请求不会稍后生效。
- [ ] 只清匹配已处理／失效草稿，不清新请求；GET 失败仍保留只读选择，取消核实与审批恢复资格分开。
- [ ] 公开请求、重启及迟到竞态验证内容指纹、旧响应过滤、再提交 409、未提交选择不进入历史、无自动审批和失败后可恢复。

## Comments

尚无实施或验收记录。
