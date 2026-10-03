# 自动预览工作目录内的本地图片

Status: ready-for-agent

实施进度：待实施

来源：[统一实施规格](../../../../.scratch/frontend-completion/PRD.md)；[公共要求与依赖总览](index.md)。

**What to build:** 自动显示 Agent Markdown 明确引用的当前工作目录图片，局部说明读取错误并可完整查看，同时保持阅读位置。

**Why:** 打通 Markdown、真实工作目录、资源身份与受控图片读取的完整路径。

**API／边界：**新增 GET workspace、resources/resolve 和 resource image；与文件工具共用根目录；BackendSession Blob、只读图片查看和可见生命周期。

**Blocked by:** [隐藏暂停读取并轮询会话状态](06-visibility-polling.md)；[安全 Markdown、网页链接与完整内容查看](07-markdown-content-viewer.md)；[恢复聊天阅读位置与自动跟随](09-chat-reading-position.md)。

## 验收条件

- [ ] 仅 Agent 明确 Markdown 图片／本地链接识别，相对／绝对／file URI 规范化，实际目标及链接不得出 workspace_root；装配时根与文件工具共用，不随 cwd 改变。
- [ ] workspace 返回 opaque 身份与 root，resolve 返回完整实际元数据／路径／版本，只有普通文件；资源绑定启动租约、目录、规范路径及版本，历史引用明确为当前磁盘内容。
- [ ] 查询纯读，无 Run／Graph／工具／文件写入；非法 422、越界／不可读 403、不存在 404、变化 409、图片超 20MiB 413、不支持 415，no-store／正确 MIME／nosniff。
- [ ] PNG／JPEG／GIF／WebP／BMP／SVG 自动预览，可进入可视区再读，同租约去重；SVG 仅 img 源，原 Markdown 路径和网页图片不直接加载。
- [ ] 受控 Blob URL 保持比例、正文宽度、约 320px 聊天高度，完整查看及原引用／实际路径核对可用；加载／失败局部保留原引用和手动重试，不改 Run。
- [ ] 隐藏、切换、租约失效停未完成读取并释放无用 URL，迟到结果失效，重新显示核实；图片尺寸变化不抢上翻锚点。
- [ ] 公开资源边界覆盖路径／链接越界、格式、大小、变更和旧租约；实机在长会话自动加载并稳定完整查看。

## Comments

尚无实施或验收记录。
