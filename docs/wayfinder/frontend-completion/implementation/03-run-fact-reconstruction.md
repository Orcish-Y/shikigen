# 全量重建消息与当前运行事实

Status: done

实施进度：已验收

来源：[统一实施规格](../../../../.scratch/frontend-completion/PRD.md)；[公共要求与依赖总览](index.md)。

**What to build:** 发送或重开会话时，以同一投影接入真实消息、流式预览、运行状态和审批事件，全量回放后不重复、不串会话。

**Why:** 让所有 UI 消费完整事实，并建立后续恢复、审批、工具与详情的共同输入。

**API／边界：**既有发送 POST SSE、Run GET stream；metadata／event／delta／error 四类公开帧；完整历史与按会话／Run 隔离的数据。

**Blocked by:** [打开会话并核实运行状态](01-open-conversation-run.md)。

## 验收条件

- [x] 历史 running／interrupted 建立既有 GET stream；完整消息按会话 seq 合并，保留公开字段和原内容结构；同 seq 完整事实覆盖预览，重复只一条。
- [x] 同 seq 多 delta 按到达顺序追加，不按文字或 seq 去重；新 GET 有效 metadata 后仅重置目标 Run 预览，metadata 前失败保留已显示正文。
- [x] 有效 SSE metadata 决定观察中 Run 当前状态，历史 lifecycle 和旧列表／快照不覆盖；终态不回退，interrupted 可继续 running，省略字段保留，null 按字段契约解释。
- [x] 持久事件按 thread_id／run_id／seq 保留与合并；同 seq 冲突和无法校验载荷作为协议问题，不伪造已确认事实；seq 空洞和一次查询缺项不删除旧事实。
- [x] GET 全量回放经后端 checkpoint／审批一致性校验，前端按 required／resolved／invalidated 重建；当前仍 interrupted 且正常回放结束才具备可审批身份，JSON 查询不替代它。
- [x] 租约、选择、Run 与观察代次共同过滤迟到帧；新 Run 从自身事实开始，切换关闭旧观察不调用 cancel；GET stream 不加 cursor 或 Last-Event-ID。
- [x] 以公开 SSE 验证重复、乱序、旧 metadata、同 seq 增量、等待审批正常 EOF 与新目标迟到，页面可演示真实发送和刷新恢复。

## Comments

### 2026-10-04：开始实施

用户指定完成第 3 票。沿用已确认的 HTTP／SSE、BackendSession、ConversationStore 公共验证边界；主 agent 实现统一投影与协议校验，最终验证由 gpt-6-luna / max 子 agent 执行。审查固定点为本轮开始前的工作副本，保存在 `.scratch/frontend-completion/ticket-03/before/`；不执行 Git 写操作。

实现已接入公开客户端与页面：`run-protocol.ts` 校验公开消息及四类 SSE；`run-projection.ts` 保存完整消息、临时预览、各 Run 元数据和持久事件；ConversationStore 负责租约／选择／观察代次及正常 EOF 的审批核实。历史查询按 seq 合并，缺项不删除；有效 GET metadata 仅重置目标 Run 的预览。省略字段保留、usage=null 表示未知，同 Run 终态不回退。审批从本次 GET required／resolved／invalidated 回放重建，审批提交按钮归第 12 票。

页面沿用现有提示、徽标、折叠原文样式；新增“生成中 · 尚未保存”、审批核实进度与只读协议原文。后端使用现有 checkpoint 校验能力，本轮未修改后端产品或 Rust 宿主。

开发先完成 12 项新增公开边界 red/green，随后根据规格审查补齐正常 EOF 快照、审批完整 ID 集合与关闭 checkpoint 防复活，最终新增用例共 21 项（包含子测试与父测试计数）。

### 2026-10-05：验收完成

由 `gpt-6-luna / max` 执行，主 agent 核对原始日志、退出码、真实请求 JSON 与截图后关闭本票。完整记录：[实施与验证报告](../../../../.scratch/frontend-completion/ticket-03/report.md)。

- 后端 6 模块专项 60 通过；完整 Python 回归一次共 290 项，289 通过、1 项 Windows symlink 权限跳过、0 失败；production ty 通过。公开 GET 探针补证 interrupted 正常 EOF、重复 body、损坏 checkpoint 核实，以及无自动 start／resume 或工具调用。
- 前端完整 48 项通过后，最后 checkpoint guard 变化再执行受影响的 3 个文件共 42 项通过，另外 9 项无关验证沿用前一批；最终 tsc／Vite build 通过。未将其描述成最终另跑完整 51 项。
- 最新构建的真实 Tauri 页面 3 项通过：显式发送并刷新恢复、interrupted GET 核实、审批继续后的旧暂停回放不覆盖 running。默认沙箱的 3 次连接失败保留，获得原生权限后同一套业务断言全通过；新增 Python 原生用例 Ruff／格式检查通过。
- 双轴审查完成：Standards 硬违规 0、重复校验已修，命名与排版为非阻塞讨论；Spec 遗留缺项／范围外改动／实现错误均为 0。
- 5173 既有服务未停止；本次 9238／45200 已释放。主 agent 已查看 WebView 截图；物理输入、IME、原生边框和多尺寸仍按第 23 票联合验收。本票不启动第 4 票，不执行 Git 写操作。
