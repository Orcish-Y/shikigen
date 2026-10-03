# 安全 Markdown、网页链接与完整内容查看

Status: ready-for-agent

实施进度：待实施

来源：[统一实施规格](../../../../.scratch/frontend-completion/PRD.md)；[公共要求与依赖总览](index.md)。

**What to build:** 按角色阅读真实正文与内容块，完整查看和复制代码／JSON；网页链接用系统默认浏览器打开，保持当前会话。

**Why:** 把完整事实变成可读内容，并提供后续工具、图片和详情可复用的只读查看入口。

**API／边界：**完整消息／预览；已确认 Markdown 解析与净化方案；Clipboard、现有前景 dialog／抽屉；受控 open_web_url 命令。

**Blocked by:** [全量重建消息与当前运行事实](03-run-fact-reconstruction.md)。

## 验收条件

- [ ] Agent 字符串安全 Markdown，用户／工具字符串原文；type=text 按角色展示，额外字段和未知块完整 JSON，数组原顺序且不跨未知块拼接，完整原数组可查看复制。
- [ ] 采用已确认 react-markdown／remark-gfm／rehype-sanitize，HTML 先文本化，不启用 raw HTML、MDX、脚本、iframe、表单；任务列表只读，表格自身滚动，脚注按消息隔离。
- [ ] 代码使用既有单色等宽外观，仅显示真实语言／可识别文件名，复制原代码无行号／围栏／提示；代码／JSON 约 320px 区内滚动，复制不截断。
- [ ] 桌面 400px 覆盖查看、窄屏底部只读面板复用单前景，关闭不改观察、输入或选择，返回有效焦点；失败保留原文可手选，预览复制明确称当前片段。
- [ ] Markdown 解析保留 Windows 本地引用供受控资源入口，原路径不直接 href／src；工具／代码／JSON 路径不自动执行，网页图片不自动请求。
- [ ] 只有 http／https 经 Rust 校验和系统浏览器打开，未知协议只读可复制；关闭 opener 自动链接旁路，Ctrl／Shift／新窗口目标遵守同入口，打开失败局部反馈。
- [ ] 公开消息、恶意／未闭合正文、块数组、复制文本和原生打开边界有可复查结果；实机核对正文层级、长表格、完整查看和单前景焦点。

## Comments

尚无实施或验收记录。
