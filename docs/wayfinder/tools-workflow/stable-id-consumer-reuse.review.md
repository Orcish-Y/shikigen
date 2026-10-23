# 14 号票验收与审查

2026-10-23，规格为 `.scratch/tools-workflow/issues/14-stable-id-consumer-reuse.md`，实现见[稳定 ID 与消费者复用](stable-id-consumer-reuse.md)。固定基线是任务开始时的 `d6ba289fc678ddb1ee566c84efd342b6883345d3`。工作区开始时干净，审查使用 `git diff <基线> --`，覆盖本票新增与修改文件；审查时尚未提交。

## 验证

| 范围 | 结果 |
| --- | --- |
| 后端全量 `python -m unittest discover -s tests -q` | 474 项，473 通过、1 项权限跳过，716.928 秒。 |
| 最终公开 API／复用接口 `python -m unittest test_tool_consumers -q` | 7 项通过，10.297 秒。包括真实子进程、三类工具传值、构建／资格／快照、完整结果及业务 `type="tool_call"`。 |
| 前端完整 `node --test tests/*.mjs` | 最终 393 项全部通过，96.961 秒。使用既有本地 ordered loader 加载同版本依赖，顺序运行。 |
| 前端首次全量及复查 | 首次 392 通过，1 项既有真实 Vite 端口测试超过其 20 秒限制；该文件随后 9 项全部通过，1.461 秒。再次完整运行 393 项通过，保留首次超时记录，不改其期限或断言。 |
| TypeScript、ty、改动范围 Ruff／格式与 `git diff --check` | 通过。 |
| Vite 正式构建 | 通过，34.98 秒；保留既有大 chunk 提示，没有变更依赖或打包配置。 |
| Windows 原生 `test_stable_identity_schema_and_complete_result` | 1 项通过，7.673 秒。正式构建、真实后端与本地 HTTP，改名后 ID 不变，来源／输入 schema／真实 JSON 结果可核对；1440px、390px 无页面横向溢出。桌面 64px 导航、256px 侧栏、48px 工具栏和 7:5 双栏断言通过。 |

专项目标先有失败用例再实现：缺少 `build_tools`，构建失败未定位工具 ID，页面缺少来源／schema 复制，以及审查发现的 LangChain 封装误判均有对应 red／green 记录。其余已有执行契约通过公开接口补足真实协作验收，没有增加私有调用次数断言。

临时日志位于 `.scratch/tools-workflow/14-*.log`，截图位于 `.scratch/tools-workflow/verification/native/test_stable_identity_schema_and_complete_result/`。已查看 1440px 和 390px 的 ID／来源概览及结构截图。原生验收最初两次失败是测试把 summary 当成 button，以及使用了不存在的退出辅助方法；修正测试后完整通过，未为此改动产品逻辑。

## Standards

独立审查通过，0 项发现。覆盖 README 的模块归属、CONTEXT 领域用语、工具页原型与公开接口测试约定；未发现需报告的代码异味。`ToolInstance` 注入执行回调，保持执行适配层不反向依赖 runtime。封装识别修复后再次独立复核，仍为 0 项发现。

## Spec

初审发现 1 项 P2：LangChain 仅凭业务对象的 `type="tool_call"` 就尝试读取封装的 id／args，导致合法业务输入在已构建工具中抛出 KeyError，直接执行却成功。

已修复：完整 ToolCall 结构交给 LangChain；只有相同 type 值的业务对象通过公开 `arun` 保留调用上下文，仍进入统一执行入口。新增公开回归同时核对直接执行、普通 `ainvoke` 和真正 ToolCall 的完整结果。独立审查者复跑该回归通过（1 项，1.348 秒），确认原问题解决，未发现新增规格偏差。

最终遗留：Standards 0 项，Spec 0 项。
