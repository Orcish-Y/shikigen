# 自动预览工作目录内的本地图片

Status: done

实施进度：已验收

来源：[统一实施规格](../../../archive/2026-10-07/development/frontend-completion/PRD.md)；[公共要求与依赖总览](index.md)。

**What to build:** 自动显示 Agent Markdown 明确引用的当前工作目录图片，局部说明读取错误并可完整查看，同时保持阅读位置。

**Why:** 打通 Markdown、真实工作目录、资源身份与受控图片读取的完整路径。

**API／边界：**新增 GET workspace、resources/resolve 和 resource image；与文件工具共用根目录；BackendSession Blob、只读图片查看和可见生命周期。

**Blocked by:** [隐藏暂停读取并轮询会话状态](06-visibility-polling.md)；[安全 Markdown、网页链接与完整内容查看](07-markdown-content-viewer.md)；[恢复聊天阅读位置与自动跟随](09-chat-reading-position.md)。

## 验收条件

- [x] 仅 Agent 明确 Markdown 图片／本地链接识别，相对／绝对／file URI 规范化，实际目标及链接不得出 workspace_root；装配时根与文件工具共用，不随 cwd 改变。
- [x] workspace 返回 opaque 身份与 root，resolve 返回完整实际元数据／路径／版本，只有普通文件；资源绑定启动租约、目录、规范路径及版本，历史引用明确为当前磁盘内容。
- [x] 查询纯读，无 Run／Graph／工具／文件写入；非法 422、越界／不可读 403、不存在 404、变化 409、图片超 20MiB 413、不支持 415，no-store／正确 MIME／nosniff。
- [x] PNG／JPEG／GIF／WebP／BMP／SVG 自动预览，可进入可视区再读，同租约去重；SVG 仅 img 源，原 Markdown 路径和网页图片不直接加载。
- [x] 受控 Blob URL 保持比例、正文宽度、约 320px 聊天高度，完整查看及原引用／实际路径核对可用；加载／失败局部保留原引用和手动重试，不改 Run。
- [x] 隐藏、切换、租约失效停未完成读取并释放无用 URL，迟到结果失效，重新显示核实；图片尺寸变化不抢上翻锚点。
- [x] 公开资源边界覆盖路径／链接越界、格式、大小、变更和旧租约；实机在长会话自动加载并稳定完整查看。

## Comments

2026-10-06：按 implement 开始实施；新增受控只读工作目录资源服务及 Blob 图片预览，复用原有详情层、可见生命周期与阅读锚点。开发专项已通过，最终验证及双轴审查待完成。用户禁止 Git 操作，本轮不暂存、不提交、不切换分支。

2026-10-06：已实现并验收。新增 workspace／resolve／image 三个纯 GET API，与文件工具共用固定根目录；Agent Markdown 本地图片自动预览、完整查看、路径复制、局部错误与重试，隐藏／切换／租约清理及段落锚点落实。显式 `gpt-6-luna / max` 验证：完整后端 329 项中 328 通过、0 失败／错误、1 Windows symlink 权限跳过，最后等价调整后 HTTP8／Ruff／ty 通过；App 逻辑修复后完整 Node 172 通过，最终 TypeScript／构建及原生 5 Python 文件 Ruff 通过。原生首批 7 项为 4 通过、1 失败、2 错误；保留夹具失败后新图片三项重验 3 通过。Spec 捕获的旧详情租约缺口先原生红灯 1 失败，修复后最终当前构建定向 1 通过；共 8 个唯一原生用例分批有通过证据，不声称一次 8／8 全绿。租约测试是公开 Tauri 桥状态帧模拟，不是实际 BackendManager 重启。Standards／Spec 无剩余硬问题，主 agent 核对七条验收证据后标记 done。Vite 583.20 kB 主 chunk 提示保留；完整过程、命令、截图及边界见[第 14 票报告](../../../archive/2026-10-07/frontend-history.zip)（包内：`docs/archive/2026-10-07/development/frontend-completion/ticket-14/report.md`）。未执行任何 Git 命令；第 15 票未开始。
