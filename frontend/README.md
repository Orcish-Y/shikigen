# Shikigen 桌面前端

基于 Tauri 2、React、TypeScript、Vite 和 Tailwind CSS 4 的桌面工作台框架。设计规范见 [design.md](design.md)。

```bash
cd frontend
pnpm install
pnpm dev         # 浏览器中查看工作台
pnpm build       # 检查类型并构建前端静态资源
pnpm tauri dev   # 启动桌面窗口
pnpm tauri build # 打包桌面应用
```

`pnpm tauri dev` 还需要安装 Rust 工具链和当前系统所需的 Tauri 原生依赖。Windows 环境安装步骤见 [Windows 开发说明](../docs/windows-development.md)。FastAPI 后端独立运行，后续可按项目根目录的 README 启动；目前前端没有连接后端。

`src-tauri/app-icon.svg` 是从项目根目录现有 `logo.svg` 居中补边得到的图标源文件。确定最终品牌图标后，可替换该文件，并运行 `pnpm tauri icon src-tauri/app-icon.svg` 重新生成应用图标。

当前支持导航展开/收起、响应式侧栏、会话过滤与切换、新建空会话、独立草稿、示例代码复制、工具结果折叠、命令面板、运行详情空态与 Markdown 导出。

页面中的对话为明确标注的示例数据，未接入后端。发送按钮禁用；会话与草稿仅保存在页面内存，刷新会重置。导航折叠偏好保存在 localStorage。

阶段完成项、验证范围与预览截图见 [前端工作台项目工作记录](work-records/2026-09-24-workbench.md)。
