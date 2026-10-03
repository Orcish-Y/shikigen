# 隐藏暂停读取并轮询会话状态

Status: ready-for-agent

实施进度：待实施

来源：[统一实施规格](../../../../.scratch/frontend-completion/PRD.md)；[公共要求与依赖总览](index.md)。

**What to build:** 可见窗口每五秒刷新第一页会话，隐藏到托盘后暂停读取但后台任务继续，重新显示立即核实并恢复当前会话。

**Why:** 将窗口生命周期接到既有读取、草稿和恢复规则，保护后台任务与列表分页进度。

**API／边界：**get_workspace_visibility、workspace-visibility-changed 的 revision／visible；现有宿主状态；第一页 GET、历史与观察读取协调。

**Blocked by:** [自动分页浏览带状态的会话列表](02-paginated-conversation-list.md)；[原文发送并保留持久消息草稿](04-message-drafts-send.md)；[断流后的有限 GET 恢复与手动重连](05-stream-recovery.md)。

## 验收条件

- [ ] 先订阅可见事件再查询，按 revision 接受，实际成功 hide／show 后更新；失焦不算隐藏，失败操作不伪造可见性，查询失败保留已知值、首次未知按可见。
- [ ] visible 且 ready 每 5 秒请求第一页，不重叠，按 ID 更新已有字段／插入并排序；失败保留列表，503 推迟下一轮，不叠额外三次重试。
- [ ] 第一页轮询不清更早页、不改下一页游标、选择或草稿；发现不同 run_id 先读历史核实，再切观察目标，旧摘要不抢新目标。
- [ ] 切换、隐藏、宿主非 ready 时停 SSE、相关 GET 和计时器，不 cancel；输入、完整事实及未知提交记录保留，未确认 POST 的中止不撤回后端执行。
- [ ] 重新显示／选择／ready 合并触发一次历史定位和适用观察恢复；同一失败轮次不被后台轮询绕过，布局与详情开关不触发重新进入。
- [ ] 公开状态输入验证订阅查询竞态和旧 startup_id 结果；真实 Tauri 验证隐藏期间任务持续、显示后当前事实更新和草稿保留。

## Comments

尚无实施或验收记录。
