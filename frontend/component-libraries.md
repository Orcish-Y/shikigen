# 前端组件库接入

第一个 HTTP 工具专项现在在真实工具页挂载 RJSF 管理表单和业务输入表单。
`src/styles.css` 已启用 `@source "../node_modules/@rjsf/shadcn"`，继续使用
现有 `--ui-*` 主题语义，不导入主题包的完整 CSS reset。
`SchemaForm` 用本地 Input/Textarea 适配基础模板和多行控件，JSON Schema
字段保留对象结构并反馈无效原文；业务表单关闭默认值填充和 format 强制校验。

工具测试结果使用本地 AI Elements Tool 适配，来源与 Reasoning 同为固定提交
[`6a9d5b1` 的 tool.tsx](https://github.com/vercel/ai-elements/blob/6a9d5b1822ffb10bba4bd97175f01edd7d8651cd/packages/elements/src/tool.tsx)，
沿用本目录已有 Apache-2.0 授权文件。它直接接收项目执行状态和完整结果，
使用 Phosphor 图标、本地 Collapsible，以及显式 JSON 格式化，确保
null、false、0、空字符串和空容器可见且可完整复制；不新增 AI SDK transport。
实际表单提交与结果行为由 `tests/tool-management-dom.test.mjs` 验证，
桌面链路由 `src-tauri/tests/tool_library_acceptance.py` 使用临时配置和本地 HTTP 服务验收。

本轮范围见 [任务导航](../.scratch/frontend-component-libraries/tickets.md)。组件位于呈现层，消息草稿、请求接受情况、运行事实和恢复仍由现有 ConversationStore、BackendClient 与运行投影负责。

02–04 的组件接入已完成。最终 `gpt-6-luna / max` 验证为前端 295/295 通过、类型检查和构建通过，真实 Tauri 原生 22/23 通过、0 跳过。剩余一条候选窗口自动化检测超时；用户截图、实际桌面 BitBlt 与 leaf UIA 已确认候选显示，人工/实机证据和自动化失败分别保留。按用户要求停止追加拼音诊断，05 保留该测试设施缺口，完整命令与证据见[验证报告](../.scratch/frontend-component-libraries/verification/report.md)。

## shadcn/ui 基础控件（02）

2026-10-13 核对的项目版本为 React / React DOM 19.3.0、Tailwind CSS / `@tailwindcss/vite` 4.3.3、Vite 7.3.6、TypeScript 5.9.3；开发检查使用 Node 24.21.0、pnpm 12.6.0。官方 [Vite 接入](https://ui.shadcn.com/docs/installation/vite)与 [Tailwind 4 / React 19 指南](https://ui.shadcn.com/docs/tailwind-v4)支持当前技术组合。

采用 **new-york-v4 / Radix** 源码路线。shadcn 是本地源码组件，未把 CLI 作为运行时依赖；核对时官方 CLI 发布版本为 4.21.4。Button、Input、Textarea 来自固定提交 `30a58d4498f270af1c1e981a7d78a15cf5740841`：

- [Button 上游源码](https://github.com/shadcn-ui/ui/blob/30a58d4498f270af1c1e981a7d78a15cf5740841/apps/v4/registry/new-york-v4/ui/button.tsx) → [本地 Button](src/components/ui/button.tsx)。
- [Input 上游源码](https://github.com/shadcn-ui/ui/blob/30a58d4498f270af1c1e981a7d78a15cf5740841/apps/v4/registry/new-york-v4/ui/input.tsx) → [本地 Input](src/components/ui/input.tsx)。
- [Textarea 上游源码](https://github.com/shadcn-ui/ui/blob/30a58d4498f270af1c1e981a7d78a15cf5740841/apps/v4/registry/new-york-v4/ui/textarea.tsx) → [本地 Textarea](src/components/ui/textarea.tsx)。

上游 MIT 授权及版权声明保存在 [shadcn-ui-MIT.txt](licenses/shadcn-ui-MIT.txt)，对应[固定版本授权原文](https://github.com/shadcn-ui/ui/blob/30a58d4498f270af1c1e981a7d78a15cf5740841/LICENSE.md)。

基础依赖使用精确版本，安装及锁文件由 pnpm 生成：

| 依赖 | 版本 | 用途 |
| --- | --- | --- |
| `@radix-ui/react-slot` | 1.3.3 | Button `asChild`，与 RJSF 的 Radix 路线一致 |
| `class-variance-authority` | 0.7.1 | 保留 Button `variant` / `size` API |
| `clsx` | 2.1.1 | 合并条件类名 |
| `tailwind-merge` | 3.7.0 | Tailwind 4 类名冲突合并 |

Slot 1.3.3 于 2026-07-24 发布，peer 支持 React 19。核对时最新 1.5.0 于 2026-10-12 发布；本次不需要它的新功能，选择已有稳定版本，保留原 pnpm 发布冷却策略。发布信息来自 [npm 包元数据](https://registry.npmjs.org/@radix-ui%2freact-slot)。

### 配置与本地适配

[components.json](components.json)声明非 RSC、TSX、new-york、Tailwind 4 CSS 和 Phosphor 图标；`@/*` 在 TypeScript、Vite 中都指向 `src/*`。`cn` 统一由 [lib/utils.ts](src/lib/utils.ts)提供，Node 的 tsx 测试也读取同一 tsconfig。

上游 Button 从 `radix-ui` 聚合入口读取 `Slot.Root`；本地使用同一 Radix primitive 的直接包 `@radix-ui/react-slot`，无需提前安装所有底层控件。保留 `variant`、`size`、`asChild`、`buttonVariants` 导出与原生属性透传；Input/Textarea 继续支持原生值、事件、标签、禁用与 React 19 ref props。以后追加组件也按其实际所需 primitive 安装。

样式按 [design.md](design.md)适配：Geist、14px 字段、紧凑按钮、6px 圆角与已有 2px 靛蓝 outline / 3px offset。未导入第二套全局 reset；去掉上游的额外焦点 ring、阴影、暗色样式与 `disabled:pointer-events-none`，保留原生禁用语义和禁用光标。Textarea 不使用上游 `field-sizing-content`，消息输入区继续由已有 48–180px 自动增高与 ResizeObserver 负责，避免两套高度机制竞争。

现有 CSS 的 `--accent` 是操作色，`--secondary` 和 `--muted` 是文字色，不能直接改为 shadcn 同名背景语义。[styles.css](src/styles.css)通过独立 `--ui-*` 映射 Tailwind 的语义色：

| shadcn / Tailwind token | 项目映射 |
| --- | --- |
| background / card / popover | `--canvas` 白色 |
| foreground | `#0f172a` 正文 |
| primary / ring | `--accent` 靛蓝 |
| primary-foreground | 白色 |
| secondary / muted | `--sidebar` 冷灰背景 |
| secondary-foreground / muted-foreground | 旧 `--secondary` / `--muted` 文字色 |
| accent / accent-foreground | `--hover` / 正文色 |
| border / input | 旧 `--border` |
| destructive / destructive-foreground | `#b91c1c` / 白色 |

原有通用按钮 hover 对 shadcn `data-slot="button"` 让位，使用 `:where` 保持旧选择器的优先级；已有按钮的操作色 hover 保留。消息主操作使用 `Button size="sm"` 并继续消费 `primary-button` 样式，窄屏沿用原有 44px 最小触控尺寸。消息草稿使用 Textarea，增加与已有状态反馈的 `aria-describedby` 关联；提交中按钮提供 `aria-busy`。取消与审批仍共用原来的主操作位置、资格和回调。

### 与后续组件的接缝

核对的 [`@rjsf/shadcn` 6.11.0](https://github.com/rjsf-team/react-jsonschema-form/blob/v6.11.0/packages/shadcn/package.json)使用 Radix 控件，React peer 为 `>=18`；其控件源码在包内，并不会因本地 Button/Input 修改而自动同步。03 负责一致版本的 RJSF 依赖并记录后续 Tailwind 扫描要求，本轮不激活扫描；以后实际表单需要按业务通过 widgets/templates 适配。

[AI Elements Reasoning](https://github.com/vercel/ai-elements/blob/main/packages/elements/src/reasoning.tsx)消费 Radix Collapsible 与可控展开状态，能够沿用当前源码组件路线。04 负责来源固定、真实推理内容和展开偏好；本票不接入 AI SDK 对话 transport、Streamdown、工具卡片或 Schema 表单。

### 公开行为与桌面验证入口

新增 [message-composer.test.mjs](tests/message-composer.test.mjs)使用 jsdom 26.1.0、Testing Library React 16.3.3 / DOM 10.4.1 / user-event 14.6.7，实际操作 Composer 和 Conversation DOM，保留真实 BackendClient / ConversationStore，模拟 HTTP 与 SSE 传输边界。仅 ResizeObserver 是无布局引擎的环境补全；高度、滚动、窄屏与 OS 输入法由 Tauri 验收负责。

```powershell
# 工作目录 C:\code\shikigen-agent\frontend
node --import tsx --test tests/message-composer.test.mjs tests/message-drafts.test.mjs
pnpm exec tsc --noEmit
```

行为覆盖原文与空白、重复点击和 Enter、pending 可编辑、接受清原版本及保留新版本、流式预览转为已提交消息、HTTP 500 unknown 不自动重发、HTTP 422 保留、IME 组合/候选确认、Shift+Enter、长按 Enter、运行/审批入口、禁用与输入焦点。jsdom 不证明 OS 候选窗口和物理键盘。

最终由轻量测试子 agent 执行完整检查和串行桌面验收：

```powershell
# 工作目录 C:\code\shikigen-agent\frontend
pnpm test
pnpm build
# 工作目录 C:\code\shikigen-agent
.venv\Scripts\python.exe frontend\src-tauri\tests\message_drafts_acceptance.py
.venv\Scripts\python.exe frontend\src-tauri\tests\native_platform_acceptance.py
```

`message_drafts_acceptance.py`复用隔离数据库、确定性执行 fixture、当前 dist 的真实 Tauri 窗口，并补充 Shift+Enter 真 WebView 换行后普通 Enter 只发一次的专项。桌面夹具端口与窗口需串行管理；最终通过数量和证据由验证报告记录，不从历史结果推断。

## RJSF 依赖准备（03）

本轮仅接入依赖，供后续工具或配置的动态表单专项使用。没有挂载 Form、业务包装组件或演示页面，也没有接管任何草稿、校验提交、工具执行或配置保存链路。

2026-10-13 从 npm 官方 registry 核对版本、engines、peerDependencies 与 exports，并在内存中读取相同版本的发布 tarball，确认实际 `lib`、`src` 和主题 CSS。四个直接依赖均精确固定为 **6.11.0**：

| 包及版本元数据 | 用途 | 必需 peers |
| --- | --- | --- |
| [`@rjsf/core`](https://registry.npmjs.org/@rjsf%2fcore/6.11.0) | Form 及 `withTheme` | React `>=18`、utils `^6.11.0` |
| [`@rjsf/utils`](https://registry.npmjs.org/@rjsf%2futils/6.11.0) | Schema、uiSchema、validator 类型与公共工具 | React `>=18` |
| [`@rjsf/shadcn`](https://registry.npmjs.org/@rjsf%2fshadcn/6.11.0) | 自带 Radix 控件的 shadcn 主题 | React `>=18`、core/utils `^6.11.0` |
| [`@rjsf/validator-ajv8`](https://registry.npmjs.org/@rjsf%2fvalidator-ajv8/6.11.0) | AJV 8 校验器 | utils `^6.11.0` |

四包均要求 Node `>=20`。项目 Node 24.21.0、React 19.3.0 满足声明；pnpm 严格 peer 安装成功。包提供 ESM 与类型 exports，真实 Node ESM 加载和项目类型检查也通过。Vite 的最终验证额外使用临时入口处理这些目前尚未进入产品入口的包，不能只以原项目构建推断 RJSF 浏览器打包成功。安装沿用既有 pnpm 发布冷却策略及 `allowBuilds.esbuild`，未添加排除项。

```powershell
# 工作目录 C:\code\shikigen-agent\frontend
pnpm add --save-exact --strict-peer-dependencies @rjsf/core@6.11.0 @rjsf/utils@6.11.0 @rjsf/shadcn@6.11.0 @rjsf/validator-ajv8@6.11.0
pnpm list @rjsf/core @rjsf/utils @rjsf/shadcn @rjsf/validator-ajv8 --depth 0 --json
```

### 真实公开导出

以下导出来自安装包本身，未使用自建包装替代：

- core 的 Form 是**默认导出**；`withTheme` 是命名导出。6.11.0 的 core 根入口没有命名 `Form`。[对应版本源码](https://github.com/rjsf-team/react-jsonschema-form/blob/v6.11.0/packages/core/src/index.ts)
- shadcn 同时导出默认 Form、命名 `Form`、`Theme`、`Widgets`、`Templates` 和各自生成函数。Form 采用 React 包装，Node 中 `typeof Form` 为 `object`，不能只接受 `function` 来判断 React 组件能否加载。[对应版本源码](https://github.com/rjsf-team/react-jsonschema-form/blob/v6.11.0/packages/shadcn/src/index.ts)
- validator 根入口导出默认校验器，以及 `customizeValidator` / `createPrecompiledValidator`。Node 构建脚本从 `@rjsf/validator-ajv8/compileSchemaValidators` 读取默认 `compileSchemaValidators` 和命名 `compileSchemaValidatorsCode`；该子路径涉及 Node 构建能力，不能导入浏览器表单入口。[对应版本源码](https://github.com/rjsf-team/react-jsonschema-form/blob/v6.11.0/packages/validator-ajv8/src/index.ts)
- utils 的 `RJSFSchema`、`UiSchema`、`ValidatorType` 为 TypeScript 类型；运行时加载检查使用真实 `createSchemaUtils` / `getDefaultFormState` 导出。

### 后续主题与校验器接入

实际渲染专项需要在 `src/styles.css` 增加以下扫描声明；路径相对于该 CSS，指向已发布包中的类名。本轮只记录要求，未添加 `@source` 或主题 CSS 导入。

```css
@source "../node_modules/@rjsf/shadcn";
```

shadcn 主题应沿用本项目的 Tailwind 4 构建以及既有 `--ui-*` 语义映射。主题包自带的 Button/Input 等源码不会自动同步本地控件，后续按实际字段需求通过 widgets/templates 接入。发布包的 `dist/default.css` 等预编译 CSS 是完整 Tailwind 构建，包含 preflight reset，整套导入可能改变工作台其他区域的视觉；本项目不需要第二次导入 reset。[6.11.0 主题 README](https://github.com/rjsf-team/react-jsonschema-form/blob/v6.11.0/packages/shadcn/README.md)

默认 `@rjsf/validator-ajv8` 使用 draft-07，并通过 ajv-formats 提供格式校验。draft-2019-09 或 draft-2020-12 需要用 `customizeValidator({ AjvClass })` 配置对应 AJV 类；官方明确说明 draft-2020-12 有破坏性变化且尚未完整验证 RJSF 组合。后续先取得真实工具 Schema 的 `$schema` 和结构，再确定支持矩阵，不能把依赖已安装视为任意 draft / `$ref` / 联合类型均可呈现。需要直接导入其他 AJV 类时，应在该专项显式声明实际使用的直接依赖，不依赖 pnpm 间接包偶然可见。[官方校验说明](https://rjsf-team.github.io/react-jsonschema-form/docs/usage/validation/)

AJV 动态编译会受到严格 CSP 的 `unsafe-eval` 限制；官方提供构建时 `compileSchemaValidators` 与浏览器侧 `createPrecompiledValidator` 的流程。当前 [Tauri 配置](src-tauri/tauri.conf.json)未显式配置 CSP，本票不修改它，也未在 WebView 中执行 Schema 校验。后续若 Schema 在运行时才出现，必须结合实际 CSP 决定如何取得匹配的预编译函数；不能把运行时注入动态代码称为已解决严格 CSP。[AJV 预编译说明](https://ajv.js.org/standalone.html)

### 验证边界

实施快速检查：严格 peer 安装 exit 0；四包 Node ESM 及构建时编译子路径均加载成功；`pnpm exec tsc --noEmit` exit 0。pnpm 提示已有 jsdom 链的 `whatwg-encoding@3.1.1` deprecated，未出现未解决的 peer 报错。

最终测试 agent 使用 [临时 Vite 构建脚本](../.scratch/frontend-component-libraries/verification/build-rjsf.mjs)，读取同目录 `rjsf-entry.ts` 的真实公开导出，沿用项目 Vite 配置，把输出单独写到 `.scratch/frontend-component-libraries/verification/rjsf-bundle/`。验证材料留在任务目录，不增加产品组件或业务重复断言测试。

```powershell
# 工作目录 C:\code\shikigen-agent
node .scratch/frontend-component-libraries/verification/build-rjsf.mjs
# 工作目录 C:\code\shikigen-agent\frontend
pnpm install --frozen-lockfile --strict-peer-dependencies
pnpm test
pnpm build
```

最终 `gpt-6-luna / max` 验证已完成严格 frozen install、真实 ESM 加载、临时浏览器构建、类型检查与正式产品构建。完整前端回归为 295/295 通过；临时 RJSF 构建处理 2412 个模块并保留 11 个真实导出。命令、首次失败与复验记录见[验证报告](../.scratch/frontend-component-libraries/verification/report.md)。真实字段渲染、可访问交互、动态 Schema、校验器与 WebView/CSP 组合属于后续表单专项，本票不把这些列为已验证。

## AI Elements 推理呈现（04）

采用 AI Elements 本地源码组件，固定上游提交 **`6a9d5b1822ffb10bba4bd97175f01edd7d8651cd`**；没有安装 CLI 或 AI SDK 运行时。[官方 Reasoning 文档](https://elements.ai-sdk.dev/components/reasoning)说明其可组合的 Reasoning / Trigger / Content API。

- [固定 Reasoning 源码](https://github.com/vercel/ai-elements/blob/6a9d5b1822ffb10bba4bd97175f01edd7d8651cd/packages/elements/src/reasoning.tsx) → [本地 AI Elements 构件](src/components/ai-elements/reasoning.tsx)。实际复用 Context、`useReasoning`、可控状态、memo 与三个构件的组合，将工作台契约作为明确本地适配。
- [固定 shadcn Collapsible 源码](https://github.com/shadcn-ui/ui/blob/30a58d4498f270af1c1e981a7d78a15cf5740841/apps/v4/registry/new-york-v4/ui/collapsible.tsx) → [本地 Collapsible](src/components/ui/collapsible.tsx)。沿用 02 的 new-york-v4 / Radix 路线，由直接 primitive 包取代聚合导入，保留标准 Root / Trigger / Content 原生 props 与 ref。
- AI Elements 的[固定上游版权与授权声明](https://github.com/vercel/ai-elements/blob/6a9d5b1822ffb10bba4bd97175f01edd7d8651cd/LICENSE)保存在 [ai-elements-LICENSE.txt](licenses/ai-elements-LICENSE.txt)，完整授权保存在 [Apache-2.0.txt](licenses/Apache-2.0.txt)。本地源码注明来源与修改；Collapsible 沿用既有 shadcn MIT 副本。

2026-10-13 实际读取源码及 npm 元数据，选用稳定精确版本，保留 pnpm 发布冷却策略：

| 依赖 | 版本 / 发布时间 | 用途 |
| --- | --- | --- |
| `@radix-ui/react-collapsible` | 1.1.12 / 2025-08-13 | 可访问折叠 primitive，React / React DOM 19 peer 兼容 |
| `@radix-ui/react-use-controllable-state` | 1.2.2 / 2025-04-18 | AI Elements 原有可控展开状态，React 19 peer 兼容 |

发布和 peer 来自 [Collapsible npm 元数据](https://registry.npmjs.org/@radix-ui%2freact-collapsible)与[可控状态 npm 元数据](https://registry.npmjs.org/@radix-ui%2freact-use-controllable-state)。使用 `pnpm add --save-exact --strict-peer-dependencies` 生成锁文件，未增加依赖冷却排除项。实际 React19 / Vite7 / Tailwind4 组合的类型与定向 DOM 检查已通过，最终构建及 WebView 组合由 05 验证。

### 工作台适配与能力边界

[ReasoningPanel](src/components/ReasoningPanel.tsx)持有原有 `isExpanded`，初始展开；它以受控 `open` 消费 AI Elements，模型内容和运行变化来自已有 MessageBody / Conversation。移除了上游基于 streaming 的自动打开、1 秒后自动关闭和本地展示时长推断，用户选择由用户操作改变。`duration` API 仅接受调用方提供的事实，本轮没有推断或显示模型思考秒数。

`ReasoningContent` 接受 ReactNode，继续使用已有 AgentText，而不使用上游的 Streamdown / Mermaid / KaTeX 插件。Markdown、安全清理、消息隔离脚注、代码原文、本地资源与桌面链接规则均沿用现有路径，没有引入 AI SDK transport、第二份消息 store 或新的 SSE 协议。根节点通过 Radix `asChild` 保持既有 section 和中文可访问名称，标题与 Phosphor 图标保留；样式继续消费原有 reasoning CSS 与 02 主题，没有新增全局 reset、动画或自动滚动。

内容始终 `forceMount` 并显式设置 `hidden={!isOpen}`。Radix 在 forceMount 下会保持内部挂载，显式 hidden 保证折叠内容退出可见及键盘访问；原始块 details、复制反馈和资源子控件保持节点身份。完整推理、原始 JSON、精确复制、空文本反馈与未知块原文入口继续保留。展开选择的生命周期仍是已挂载面板；切换会话导致面板重新挂载时沿用原有初始展开，没有新增持久偏好存储。

现有后端只产生正文增量：GraphEventAdapter 读取可见文本，RunSseEncoder 固定 `field: "content"`，RunProjection 忽略 reasoning 增量字段。**本轮不增加后端推理增量能力**。DOM 测试通过 MessageBody 的公开 `preview` / `generating` props 检查推理预览标签与状态切换；真实 Tauri 验收通过保存的 reasoning 消息和同一运行后续正文流，分别证明真实推理、流式预览和用户阅读行为，不把 props 测试称作后端推理流证据。

### 检查与真实桌面入口

[reasoning-dom.test.mjs](tests/reasoning-dom.test.mjs)操作真实 MessageBody / Conversation，并复用真实 BackendClient / ConversationStore 的 HTTP/SSE 边界。覆盖用户展开选择、持续更新、键盘与焦点、子节点挂载、完整原文与复制失败、未知/空内容，以及保存/预览/取消/失败语义。开发定向 6 项和既有消息呈现 11 项共 17 项通过；TypeScript 检查通过。

[确定性模型夹具](../tests/desktop_reasoning_fixtures.py)先由真实 LangChain Agent 保存标准 reasoning 内容和工具调用，再生成可控的正文增量，两个 marker 分别释放正文更新和完成；不访问模型网络。LangChain v3 会对标准块增加 index、对未知块保留原始 value，并在内容中记录 tool_call。验收使用独立固定的 `SAVED_CONTENT` / `SAVED_ANSWER_CONTENT` 期待，对公开保存表示与推理原文字节分别核对；取消后的正文是既有 Runtime 封存的字符串。

[Tauri reasoning_acceptance.py](src-tauri/tests/reasoning_acceptance.py)沿用 MessageDraftAcceptance / ReconstructionAcceptance 和阅读验收基础，使用真实 `__TAURI_INTERNALS__`、HTTP/SSE、隔离 SQLite、trusted CDP 键盘输入和实际布局。两个新方法覆盖正文更新期间折叠/焦点/阅读锚点、完整查看、原始及未知 JSON、复制失败反馈、390px 窄窗与弹层焦点、会话和草稿隔离、实际取消确认与中止消息。复制内容检查注入的是外部 clipboard 边界，不代表系统剪贴板或实体键盘证据。两条完整桌面方法已由 `gpt-6-luna / max` 独立执行并通过，结果见[验证报告](../.scratch/frontend-component-libraries/verification/report.md)。

首次执行在 Enter 展开步骤失败；真实 WebView 事件对照证实测试辅助方法只发送 keyDown/keyUp，缺少字符事件。仅为 Enter keyDown 补齐 `text` / `unmodifiedText` 后，两条原业务场景从正式源码复验通过，没有修改组件、业务断言或超时。系统 IME 候选窗口属于另一条独立验收，不从 CDP 按键结果推断其通过。

```powershell
# 工作目录 C:\code\shikigen-agent\frontend，开发定向
node --import tsx --test tests/reasoning-dom.test.mjs tests/message-content.test.mjs
pnpm exec tsc --noEmit

# 工作目录 C:\code\shikigen-agent，当前 frontend/dist 构建完成后串行运行
$env:PYTHONPATH = (Join-Path $PWD 'tests') + [IO.Path]::PathSeparator + (Join-Path $PWD 'packages/harness')
.venv\Scripts\python.exe frontend\src-tauri\tests\reasoning_acceptance.py
```

9238 / 45200 端口需要空闲；5173 只复用逐字节匹配当前 dist 的静态服务或由夹具自行启动。最终串行 runner 的产物位于 `.scratch/frontend-component-libraries/verification/native/<类名>/<方法名>/`，包含 result.json、host 日志和截图。完整前端回归、构建和原生新方法由 05 的 `gpt-6-luna / max` 测试 agent 执行；jsdom 的无布局补全、系统输入法候选窗口、OS 剪贴板与实体硬件各自记录覆盖边界。
