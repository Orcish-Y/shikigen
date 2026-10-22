# 12 号票审查与验证

需求：[测试取消、超时与运行中交互](../../../.scratch/tools-workflow/issues/12-test-cancellation-lifecycle.md)。实现说明见[测试生命周期](test-cancellation-lifecycle.md)。

以下两轴审查与全量证据记录初次实现，后续各节保留中间调整历史。当前协议以实现说明和文末“单次请求开始测试”为准，独立登记流程已按用户决定移除。

本次开发起点为 `f5dddbc65ba6dbcabaa9da59946d96e2c5335fef`。提交前审查命令为 `git diff f5dddbc65ba6dbcabaa9da59946d96e2c5335fef --`，包含已暂存的新文件和工作区修复；起点到当前 HEAD 的提交列表为空，因此没有用空的 `...HEAD` 差异代替本次改动。

## Standards

独立审查依据 `frontend/design.md`、`frontend/component-libraries.md`、README 的依赖方向、工具模块布局和定义／适配器决议。仓库未发现 AGENTS.md、CLAUDE.md、CODING_STANDARDS.md、CONTRIBUTING.md、GLOSSARY.md；同时使用 code-review 技能的 12 项 smell baseline，区分规范硬违规与判断性建议。

初审没有硬违规，1 项低优先级 Mysterious Name 建议：响应有效性计数使用 `testObservation`／`observation`，已更名为 `testObservationRevision`／`observationRevision`。

最终复核：文档规范硬违规 0，判断性建议 0；没有引入兼容别名、无关抽象或改变模块依赖方向。

## Spec

初审发现 1 项 P1：开始响应丢失后释放编辑锁，已接收测试却没有可恢复身份。补充客户端开始前生成的 UUID、明确拒绝与启动不确定状态、同身份观察及开始前取消；以公开 API 和真实组件先复现再修复。原生验收在页面启动前安装 fetch 故障注入，真实发出请求、丢弃 202 响应后仍可查询／取消且业务只调用一次。

复核发现 1 项 P2：pending 取消先查原始 UUID、后规范化，可能覆盖已有运行观察。改为先统一 UUID 再查找／创建，补充大写且无连字符身份的取消验证，要求 3 秒内完成并关闭实际服务连接。旧实现会等业务预算耗尽，修复后通过。

另补充重复敏感 URL 查询参数验证；遍历全部查询参数对，防止 `dict(parse_qsl(...))` 丢弃前一个已知密钥值。

最终复核：0 个剩余发现，原 P1／P2 均关闭；未发现明确缺项或范围扩张。

两轴最终计数：Standards 0，Spec 0。

## 验证证据

按需求指定的公开 API、真实本地资源和工作区／结果组件边界实施。开始缺少取消接口、HTTP 读取中断丢失详情、凭据回显、开始身份丢失和 UUID 格式变体均有失败测试再修复的证据；未对私有方法建立镜像测试。

| 检查 | 结果与记录 |
| --- | --- |
| 后端全量 `python -m unittest discover -s tests` | 451 项，450 通过、1 跳过，585.503 秒；`.scratch/tools-workflow/12-backend-full.log`。 |
| 审查修复后相关后端回归 | 执行器、工具库、Python、两种 MCP、OpenAPI 和新生命周期 API 共 103 项通过，136.038 秒；`12-backend-final.log`。 |
| 最终生命周期 API 专项 | 8 项通过，包含真实进程／连接关闭、初始化预算、重复参数脱敏和身份竞态；`12-api-final.log`。 |
| 前端全量 | 全部 34 个测试文件独立进程运行，386 项通过；`12-frontend-full.log`。 |
| 审查修复后工作区 DOM 回归 | 42 项通过，含新增开始响应丢失／迟到开始测试；`12-dom-final.log`。全量运行发生在此新增测试前，其余文件没有再改动。 |
| TypeScript 与生产构建 | `tsc --noEmit` 通过，Vite 35.05 秒通过；`12-typecheck-final.log`、`12-build-final.log`。仅有既存的大 chunk 提示。 |
| 真实 Windows WebView | 新原生方法 1 项通过，8.235 秒；`12-native-final.log`。覆盖丢失真实 202、四种终态、取消后草稿选择、1440／390px 可达性、无溢出及原型尺寸，截图已目视检查。 |
| Python 静态检查 | 受影响文件 Ruff check／format 和 `ty check packages/harness/shikigen app` 通过；Git 差异空白检查通过。 |

全量后新增的身份处理与脱敏修复已由最终 103 项后端回归、42 项 DOM 回归及新构建／原生验收复核，没有重复运行未受影响的整套测试。

Windows 下图标包的 ESM 入口加载较慢，jsdom 全量使用本地临时加载器选取同一版本发布包的 CommonJS 图标入口，并逐文件隔离运行；未改产品依赖或生产入口。生产 Vite 构建及原生 WebView 使用正式入口。临时加载器、日志和截图保留在忽略的 `.scratch/tools-workflow/`，不随本次提交。

## 后续调整：后端登记测试身份

用户指出前端状态参数可能误传、取消占位集合在开始不再到达时不会释放，因此移除取消接口的 `pending` 参数及 `_pending_test_cancellations`。

页面先通过 `POST /api/tools/tests/reservations` 获得后端生成并登记的身份，再提交开始请求。取消只处理后端已知记录；未知身份返回 404。未使用登记 30 秒后过期，在观察或分配容量时核对并回收；取消或过期记录被淘汰后，携带旧身份的开始请求也只能返回 404。登记失败、失联或被前端取消时不发送业务请求；迟到登记响应也不触发业务。

验证保持在公开 API 和真实组件边界：未知取消不占容量、登记可在执行前取消、过期登记释放容量、淘汰身份不能重新执行、定义被拒绝后立即结束登记、登记阶段取消／失联、迟到响应及开始响应丢失均有覆盖。时间边界使用时钟替身，不依赖固定 sleep。

- 后端相关回归 105 项通过，137.448 秒：`.scratch/tools-workflow/12-registration-backend.log`。
- 工作区 DOM 回归 43 项通过，47.253 秒：`12-registration-dom.log`。
- TypeScript、Vite 生产构建通过（117 秒）：`12-registration-typecheck.log`、`12-registration-build.log`。
- 真实 Windows WebView 1 项通过，14.756 秒；验证开始请求使用后端登记的身份，丢失真实 202 后仍可取消并完成草稿离开，桌面／窄屏尺寸检查通过：`12-registration-native.log`。
- Python Ruff、ty 和 Git 空白检查通过。

## 后续调整：统一测试快照状态

用户指出 `phase` 和 `status` 含义重复，快照改为只保留 `status`：`reserved`、`running`、`success`、`error`、`timeout`、`cancelled`。登记时明确返回待执行，开始执行时转为运行中，所有结束路径直接写入对应终态。删除 `phase` 及单独的 `finished` 表达。

前端统一判断待执行和执行中为活动状态，保持编辑锁、轮询和取消能力；后端回收容量时同样排除这两种状态。状态文案在最近测试、侧栏和结果组件之间复用。

公开 API 回归验证登记／查询只返回统一状态、待执行不触发业务、登记仍占用活动容量，以及取消、过期和开始拒绝的终态。工作区回归补充开始响应丢失后连续查询到待执行仍保持锁定和轮询，取消后迟到开始响应不能恢复测试。

- 工作区 DOM 回归 43 项通过，130.446 秒：`.scratch/tools-workflow/12-single-status-dom.log`；结果组件状态文案复用调整后，相关 3 项复核通过：`12-single-status-result-dom.log`。
- 后端工具库、Python、stdio MCP、HTTP MCP 和生命周期 API 共 84 项通过，243.695 秒：`12-single-status-backend.log`。
- Vite 生产构建通过（86 秒）：`12-single-status-build.log`；真实 Windows WebView 1 项通过，15.696 秒，覆盖开始失联后的取消、草稿离开和桌面／窄屏交互：`12-single-status-native.log`。
- TypeScript、Python Ruff／ty 和 Git 空白检查通过。

## 后续调整：集中保存测试记录和任务

用户指出测试记录与执行任务无需按同一身份分别维护两个字典。删除 `_tasks`，统一使用 `_test_records: dict[str, ToolTestRecord]`；记录同时持有快照、登记截止时间及可选 `asyncio.Task`。创建函数相应改名为 `_create_test_record`，直接返回完整记录。

执行完成回调清空记录中的任务引用，保留终态快照；取消及关闭直接使用同一记录中的任务，保留等待资源清理和重复取消保护。容量回收同时要求终态及任务引用为空，防止清理未结束时淘汰记录。对外观察仍只返回快照。

新增公开接口回归：一项执行和 99 项待执行登记占满容量，执行完成后可回收其记录、其余登记保持可查询；同时持有待执行登记和两个真实 HTTP 执行时，关闭后全部取消并关闭实际连接。

- 后端生命周期与工具库接口回归共 43 项通过，95.395 秒：`.scratch/tools-workflow/12-record-task-backend.log`，包含真实 Python、HTTP 和两种 MCP 的取消／超时清理。
- Python Ruff check／format、ty 和 Git 空白检查通过。

## 后续调整：单次请求开始测试

用户选择简化低概率的开始响应丢失处理，开始请求同时创建测试身份并启动执行，202 响应返回后端生成的 ID。删除登记接口、客户端开始身份参数、`reserved` 状态、登记截止时间和过期扫描，保留集中管理快照与任务的 `ToolTestRecord`。

正常取得 ID 后继续查询、取消并等待资源清理。响应丢失而没有 ID 时，前端明确显示启动结果不确定，保持锁定且不自动重试；用户可选择停止等待，再按原规则处理未保存草稿。停止等待仅结束前端观察，不伪造取消或断言尚未执行；未知后端执行仍受工具超时及后端关闭清理约束。

公开接口回归验证单次开始生成 UUID、拒绝调用方传入身份、登记接口移除、未知取消不占容量、100 项实际活动执行的容量保护和完成回收。工作区回归验证无前置登记、丢失响应后不重复执行或发送未知身份查询／取消、停止等待保留草稿、迟到响应隔离及明确拒绝可修正。原生验收保留正常取消／超时／成功／失败及响应式布局，并额外丢弃真实 202，验证无 ID 状态、无自动重试及后端实际超时。

- 后端生命周期、工具库和 Python 接口回归覆盖 61 项：首轮 60 项通过，唯一失败为登记接口移除后的响应码断言（已有查询路径仍匹配该 URL，POST 返回 405）；修正断言后启动身份专项 1 项通过，2.376 秒：`.scratch/tools-workflow/12-single-start-backend.log`、`12-single-start-identity.log`。
- 工作区 DOM 回归 43 项全部通过，128.804 秒：`12-single-start-dom.log`。
- TypeScript 和 Vite 生产构建通过（95 秒）：`12-single-start-typecheck.log`、`12-single-start-build.log`。
- 真实 Windows WebView 1 项通过，14.896 秒：`12-single-start-native.log`。
- Python Ruff check／format、ty 和 Git 空白检查通过。
