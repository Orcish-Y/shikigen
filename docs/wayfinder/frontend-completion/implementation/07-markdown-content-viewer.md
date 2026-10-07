# 安全 Markdown、网页链接与完整内容查看

Status: done

实施进度：已验收

来源：[统一实施规格](../../../archive/2026-10-07/development/frontend-completion/PRD.md)；[公共要求与依赖总览](index.md)。

**What to build:** 按角色阅读真实正文与内容块，完整查看和复制代码／JSON；网页链接用系统默认浏览器打开，保持当前会话。

**Why:** 把完整事实变成可读内容，并提供后续工具、图片和详情可复用的只读查看入口。

**API／边界：**完整消息／预览；已确认 Markdown 解析与净化方案；Clipboard、现有前景 dialog／抽屉；受控 open_web_url 命令。

**Blocked by:** [全量重建消息与当前运行事实](03-run-fact-reconstruction.md)。

## 验收条件

- [x] Agent 字符串安全 Markdown，用户／工具字符串原文；type=text 按角色展示，额外字段和未知块完整 JSON，数组原顺序且不跨未知块拼接，完整原数组可查看复制。
- [x] 采用已确认 react-markdown／remark-gfm／rehype-sanitize，HTML 先文本化，不启用 raw HTML、MDX、脚本、iframe、表单；任务列表只读，表格自身滚动，脚注按消息隔离。
- [x] 代码使用既有单色等宽外观，仅显示真实语言／可识别文件名，复制原代码无行号／围栏／提示；代码／JSON 约 320px 区内滚动，复制不截断。
- [x] 桌面 400px 覆盖查看、窄屏底部只读面板复用单前景，关闭不改观察、输入或选择，返回有效焦点；失败保留原文可手选，预览复制明确称当前片段。
- [x] Markdown 解析保留 Windows 本地引用供受控资源入口，原路径不直接 href／src；工具／代码／JSON 路径不自动执行，网页图片不自动请求。
- [x] 只有 http／https 经 Rust 校验和系统浏览器打开，未知协议只读可复制；关闭 opener 自动链接旁路，Ctrl／Shift／新窗口目标遵守同入口，打开失败局部反馈。
- [x] 公开消息、恶意／未闭合正文、块数组、复制文本和原生打开边界有可复查结果；实机核对正文层级、长表格、完整查看和单前景焦点。

## Comments

2026-10-05：已实现角色正文、完整代码／JSON 查看与复制、受控网页打开及弹层焦点恢复／循环，沿用现有 Slate、单色代码和靛蓝焦点样式。最终验证及两轴审查由显式 `gpt-6-luna / max` 子 agent 执行，主 agent 核对日志、复制／焦点记录和最新截图：前端111项、Rust25项、本票真实Tauri2项及旧03／04／05／06共10项通过，类型／构建／Ruff通过。实现中实际焦点问题和测试oracle修正的失败证据保留；验收映射见[第07票报告](../../../archive/2026-10-07/frontend-history.zip)（包内：`docs/archive/2026-10-07/development/frontend-completion/ticket-07/report.md`）。

完整后端291项为289通过、1退出超时错误、1 Windows权限跳过；原错误用例隔离两次通过，原因未确认，见[独立问题](../../../issues/empty-host-environment-startup-exit.md)。本票关闭不表示完整仓库回归通过。窄屏为真实WebView设备视口模拟；物理窗口、IME与边框联合检查仍归23票。完整工具关联／卡片属于下一票08，本轮未启动。
