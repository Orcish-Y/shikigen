# 2026-09-24：前端页面框架（历史阶段）

本记录仅描述页面框架阶段，未重新运行该阶段验收。2026-10-02 的 Windows 后端托管、真实业务接入和日志能力见 [当前收尾摘要](../../docs/windows-backend-lifecycle.md)。

**做什么**：将两份 HTML demo 组织成 React/Tauri 工作台，覆盖导航展开/收起、历史过滤、示例消息、会话草稿、代码复制、命令面板、详情空态、Markdown 导出与响应式布局。

**为什么**：先明确展示与组件边界，为真实 Thread/Run、流式输出与审批提供页面基础。

**用什么 API**：React、CSS Grid/Flex、localStorage、Clipboard、Blob、原生 dialog 与 Tauri。当时使用静态示例数据，发送禁用，HTTP/SSE 未接入；这些描述不是当前桌面能力。

## 当时验收与限制

- TypeScript/Vite 构建通过；Chromium 检查导航尺寸、草稿隔离、历史过滤、新建、导出触发、弹层和快捷键。
- 1440×900、1280×800、1024×768、390×844 完成浏览器检查；后三种显式检查无横向溢出和输入区位置。
- 当时没有 Tauri 原生启动、打包、真实模型/HTTP/SSE 或审批恢复验收。剪贴板内容、工具折叠和导出正文也没有完整断言。

五张尺寸/导航截图已集中到 [视觉归档](../../docs/archive/2026-10-02/visual-explorations.zip)，路径仍为 `frontend/work-records/assets/2026-09-24-frontend-workbench/`。完整旧记录保存在 [整理前文档包](../../docs/archive/2026-10-02/edited-documents-before-cleanup.zip)。

设计基准的现路径：[展开原稿](../../design/demo-菜单展开.html)、[折叠原稿](../../design/demo-菜单折叠.html)；开发材料：[设计规范](../design.md)、[前端 PRD](../../docs/frontend/frontend-prd.md)、[运行方式](../README.md)。链接于 2026-10-03 按当前文件位置更新；本记录的开发事实仍属于 2026-09-24，组件文件组织与当前数据流以现有代码为准。
