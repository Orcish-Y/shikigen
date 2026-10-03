# 执行失败后保存已生成的中止正文

Status: ready-for-agent

实施进度：待实施

来源：[统一实施规格](../../../../.scratch/frontend-completion/PRD.md)；[公共要求与依赖总览](index.md)。

**What to build:** 执行实际失败时保存已接入正文，展示真实失败原因和独立中止标记，重新读取后仍保留。

**Why:** 将取消建立的原子结算用于失败，保证同一历史记录在竞争、回滚与后续运行中稳定。

**API／边界：**实际运行失败结算、既有中止正文事务和 generation_status=error；生命周期、历史／Run messages 和公开快照。

**Blocked by:** [确认取消并保存已生成的中止正文](10-cancel-partial-message.md)。

## 验收条件

- [ ] 实际 Run 失败保存全部已接入非空未提交 AI 正文，原身份／seq／空白保留，正文外标因失败中止，已有 complete 消息和工具记录不改。
- [ ] 正文、Run error、实际 error／code、生命周期同事务，成功后发布；写失败无假保存／终态成功，保留可重试所有者，不靠查询重跑或补写。
- [ ] 取消与失败遵循首个有效终态，重复或晚到结算不改 generation_status／原因；后续 Graph 根快照不把封存身份当新 Run 的新消息，晚到用量可继续结算。
- [ ] 连接故障、工具 status=error、资源错误和 interrupted 不触发此保存；未知 generation_status 按协议问题保留可读数据。
- [ ] 前端终态补读与保存确认复用取消路径，未确认预览不导出，实际失败原因可完整核对。
- [ ] 公开执行与持久查询覆盖失败途中正文、空正文、多消息、回滚、取消竞争、晚到快照和下一 Run 历史重放；实机重新进入仍可读。

## Comments

尚无实施或验收记录。
