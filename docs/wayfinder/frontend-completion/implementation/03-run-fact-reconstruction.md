# 全量重建消息与当前运行事实

Status: ready-for-agent

实施进度：待实施

来源：[统一实施规格](../../../../.scratch/frontend-completion/PRD.md)；[公共要求与依赖总览](index.md)。

**What to build:** 发送或重开会话时，以同一投影接入真实消息、流式预览、运行状态和审批事件，全量回放后不重复、不串会话。

**Why:** 让所有 UI 消费完整事实，并建立后续恢复、审批、工具与详情的共同输入。

**API／边界：**既有发送 POST SSE、Run GET stream；metadata／event／delta／error 四类公开帧；完整历史与按会话／Run 隔离的数据。

**Blocked by:** [打开会话并核实运行状态](01-open-conversation-run.md)。

## 验收条件

- [ ] 历史 running／interrupted 建立既有 GET stream；完整消息按会话 seq 合并，保留公开字段和原内容结构；同 seq 完整事实覆盖预览，重复只一条。
- [ ] 同 seq 多 delta 按到达顺序追加，不按文字或 seq 去重；新 GET 有效 metadata 后仅重置目标 Run 预览，metadata 前失败保留已显示正文。
- [ ] 有效 SSE metadata 决定观察中 Run 当前状态，历史 lifecycle 和旧列表／快照不覆盖；终态不回退，interrupted 可继续 running，省略字段保留，null 按字段契约解释。
- [ ] 持久事件按 thread_id／run_id／seq 保留与合并；同 seq 冲突和无法校验载荷作为协议问题，不伪造已确认事实；seq 空洞和一次查询缺项不删除旧事实。
- [ ] GET 全量回放经后端 checkpoint／审批一致性校验，前端按 required／resolved／invalidated 重建；当前仍 interrupted 且正常回放结束才具备可审批身份，JSON 查询不替代它。
- [ ] 租约、选择、Run 与观察代次共同过滤迟到帧；新 Run 从自身事实开始，切换关闭旧观察不调用 cancel；GET stream 不加 cursor 或 Last-Event-ID。
- [ ] 以公开 SSE 验证重复、乱序、旧 metadata、同 seq 增量、等待审批正常 EOF 与新目标迟到，页面可演示真实发送和刷新恢复。

## Comments

尚无实施或验收记录。
