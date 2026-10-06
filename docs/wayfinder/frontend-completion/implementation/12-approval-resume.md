# 逐项审批并继续同一运行

Status: done

实施进度：已验收

来源：[统一实施规格](../../../../.scratch/frontend-completion/PRD.md)；[公共要求与依赖总览](index.md)。

**What to build:** 在聊天卡片核对真实动作与参数，逐项批准或拒绝，统一提交后继续同一 Run，并可经确认取消。

**Why:** 提供首版审批主路径，复用已经可靠的观察、参数查看和写操作互斥。

**API／边界：**GET stream 校验后的 required／resolved／invalidated；既有 approval-decisions POST；同 Run 写 pending 与取消入口。

**Blocked by:** [确认取消并保存已生成的中止正文](10-cancel-partial-message.md)。

## 验收条件

- [x] 按事件 seq 呈现真实请求卡片，Interrupt／动作原顺序、namespace、工具名、description 和 allowed_decisions 可读，空 namespace 主流程但原值保留。
- [x] 默认未选择、无批量按钮，只显示受支持允许选项，显示 X／Y，全部 Interrupt 全部动作选完一次提交；不可解析／不支持时整组只读并保留核实和取消。
- [x] 参数默认折叠，可完整 JSON／复制／放大只读，详情不编辑或再审批；拒绝原因可选，切批准隐藏保留，批准不带 message，非空拒绝按原文。
- [x] responses 覆盖全部当前 Interrupt，decisions 保持动作顺序；checkpoint 用客户端身份保护，现有 body 不加 checkpoint 或客户端条件提交标识。
- [x] 提交锁定本组编辑／提交／取消，本次有效 POST metadata 即结束 pending 并继续观察，不等 EOF，不把 GET／旧 metadata 当接受。
- [x] 状态与实际 resolved／invalidated 收敛，HTTP 200／本地选择不造历史；Run 终态旧卡片立即不可操作，拒绝动作不直接将 Run 变 cancelled。
- [x] 底部处理审批定位唯一卡片，running 底部取消，卡片内统一提交／取消；卡片尚未恢复时定位提示与恢复入口。
- [x] 公开决策与实机验证多 Interrupt／多动作、批准／拒绝、工具在决策前未执行、同 run_id 继续、pending 竞争及不能支持的动作。

## Comments

2026-10-06：按 /implement 开始第 12 票。复用既有审批 POST、取消确认、GET stream 校验、内容抽屉与事件投影；应用内选择绑定完整请求身份。最终验证交由显式 gpt-6-luna / max 子 agent，跨重启审批草稿仍由第 13 票实施。

2026-10-06：八条验收满足并标记 done。gpt-6-luna / max 验证最终 Node 152 通过、后端完整 321 项中 320 通过／1 Windows 符号链接权限跳过、最终 HTTP 专项 1 通过、最终 Tauri 定向 7 通过；分批覆盖 12 个唯一原生用例，先前环境失败及业务失败不改算通过。TypeScript、构建、产品 ty、三文件 Ruff 通过；新增 Graph 测试仍有两条 ty TypedDictLike 兼容诊断，官方状态类型可复现，未忽略或算通过。Standards／Spec 无剩余硬问题。逐条证据、命令、截图、历史失败及范围见[本票报告](../../../../.scratch/frontend-completion/ticket-12/report.md)。
