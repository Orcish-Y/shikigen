# 确认取消并保存已生成的中止正文

Status: ready-for-agent

实施进度：待实施

来源：[统一实施规格](../../../../.scratch/frontend-completion/PRD.md)；[公共要求与依赖总览](index.md)。

**What to build:** 运行中或等待审批时经确认取消，立即看到真实终态，并在重开后读取取消前后端已接入的全部正文。

**Why:** 把取消成功与正文保存连成真实事务，同时控制写请求竞争和未知结果。

**API／边界：**既有 cancel POST 与 RunSnapshot；运行／消息／事件原子提交、AI generation_status；Run messages 补读、GET 核实和共享写 pending。

**Blocked by:** [原文发送并保留持久消息草稿](04-message-drafts-send.md)；[断流后的有限 GET 恢复与手动重连](05-stream-recovery.md)；[安全 Markdown、网页链接与完整内容查看](07-markdown-content-viewer.md)。

## 验收条件

- [ ] 新 AI 显式 generation_status=complete／cancelled／error，旧缺省 complete 兼容幂等；取消取所有非空未提交正文，原 message_id／预留 seq、原片段顺序和空白保留，不造部分 tool_calls 或空消息。
- [ ] 中止正文、Run cancelled、生命周期与必要审批失效同事务，成功后再封口发布并请求协作停止；取消快照返回时共同持久化，已发生工具副作用不保证停止／撤销。
- [ ] 正常消息先提交保留 complete，封存先提交保留 cancelled，首个有效终态获胜；迟到 delta／Graph 快照不改正文，回滚保留缓冲与结算所有者，纯 GET 不补写。
- [ ] 每次取消一次同风格确认，文案说明副作用，继续运行／确认取消，默认继续运行；Esc／关闭／遮罩零 POST，确认时重核目标／租约，切换／隐藏／失效关闭。
- [ ] 同 Run 写 pending 互斥；核实取消只需同一非终态状态，不要求审批可解析或选完。有效快照及时结束 pending，completed／error 如实显示，异常身份／非终态响应只 GET 核实。
- [ ] 取消未知或失败保留记录、按 Retry-After 与有限 GET 核实，非终态时仅恢复人工确认；不自动 POST，不用 AbortController 代替取消。
- [ ] 完整中止事实替换预览并独立标因取消中止；终态一次 Run messages 补读，未确认内容仍预览并提示保存读取，失败可手动，重复通知不重复补读。
- [ ] 公开查询和故障注入验证取消／完成竞争、原 seq、回滚、重复封存、断开取消请求、等待审批失效；实机确认后重开正文完整可读。

## Comments

尚无实施或验收记录。
