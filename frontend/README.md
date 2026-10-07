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

`pnpm dev` 与 `pnpm tauri dev` 优先使用 5173，端口被占用时自动尝试后续端口。桌面启动脚本先启动 Vite，再将实际地址传给 Tauri；托管后端的 CORS 同时使用本次前端 origin（由启动脚本通过环境传递），终端会打印本次地址，无需结束占用端口的其他程序。请使用 `pnpm tauri dev` 进入此启动流程；直接运行 `pnpm exec tauri dev` 或 `cargo tauri dev` 使用固定地址，遇到占用仍会报错。`pnpm tauri build` 等其他命令继续转交给 Tauri CLI。

截至 2026-10-07，首版 23 张实施票据已完成，包含真实会话、HTTP/SSE、恢复、审批、取消、资源、导出、详情与用量；结果及未覆盖范围见 [原生验收汇总](../docs/wayfinder/frontend-completion/native-acceptance-summary.md)。关窗隐藏到托盘，显式退出回收后端；直接浏览器访问仍为示例预览。macOS 原生与安装包分发尚未验收。近期端口回退和网络模块改动见 [开发交接](../docs/development-handoff.md)。

当前实现和测试入口见 [Windows 生命周期收尾](../docs/windows-backend-lifecycle.md)。导航、历史、草稿、命令面板、代码复制、导出与响应式布局的早期阶段记录见 [2026-09-24 工作记录](work-records/2026-09-24-workbench.md)，旧截图在归档包内。

`src-tauri/app-icon.svg` 来自根目录现有 `logo.svg`；替换图标源后可运行 `pnpm tauri icon src-tauri/app-icon.svg` 重新生成应用图标。现有应用图标属于产品资源，本次文档清理保留。
