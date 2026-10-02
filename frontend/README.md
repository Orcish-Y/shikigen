# Shikigen 桌面前端

基于 Tauri 2、React、TypeScript、Vite 和 Tailwind CSS 4。设计规范见 [design.md](design.md)，文档入口见 [总导航](../docs/README.md)。

```bash
cd frontend
pnpm install --frozen-lockfile
pnpm dev         # 浏览器示例预览
pnpm build       # TypeScript 检查与 Vite 构建
pnpm tauri dev   # 桌面窗口，自动启动托管 Python 后端
pnpm tauri build # 构建命令；安装包及 Python 分发尚未完成验收
```

Windows 环境准备见 [开发说明](../docs/windows-development.md)。桌面需要项目根目录的 Windows `.venv`、有效 `config.json` 和模型所需环境变量；Python 入口加载根目录 `.env`。桌面开发时无需另外启动 Uvicorn，同数据路径的独立 HTTP/CLI 会争用运行数据锁。托管模式关闭 reload，Python 变更后从托盘退出并重新打开。

截至 2026-10-02，Windows 开发态桌面就绪后读取真实 Thread、消息、Run 和用量，支持显式发送、HTTP/SSE、刷新恢复观察、换端口重试隔离及错误页启动日志。关窗隐藏到托盘，显式退出回收后端；直接浏览器访问仍为示例预览。审批提交界面、完整取消交互、macOS 原生与安装包分发不能视为已验收。

当前实现和测试入口见 [Windows 生命周期收尾](../docs/windows-backend-lifecycle.md)。导航、历史、草稿、命令面板、代码复制、导出与响应式布局的早期阶段记录见 [2026-09-24 工作记录](work-records/2026-09-24-workbench.md)，旧截图在归档包内。

`src-tauri/app-icon.svg` 来自根目录现有 `logo.svg`；替换图标源后可运行 `pnpm tauri icon src-tauri/app-icon.svg` 重新生成应用图标。现有应用图标属于产品资源，本次文档清理保留。
