# Windows 本地开发

项目位置：`C:\code\shikigen-agent`。使用 Windows PowerShell 打开本项目。

## 环境

- Windows 版 uv 与 Python 3.12：`uv sync --locked` 会准备项目的 `.venv`。
- Node.js 22.12+ 或满足 Vite 7 要求的更新版本，以及 pnpm 12.6.0。
- Rust MSVC 工具链、Microsoft C++ Build Tools（“使用 C++ 的桌面开发”工作负载）和 WebView2 Runtime。
- Tauri 官方说明：https://v2.tauri.app/zh-cn/start/prerequisites/

Linux 的 `.venv`、`node_modules` 和 Rust `target` 不可复用，锁文件继续保留。
VS Code 的默认解释器位置指向 `.venv` 目录，让 Python 扩展识别平台对应的可执行文件。
如果编辑器记住了旧路径，执行“Python: Select Interpreter”，选择 `.venv\Scripts\python.exe`。

## 安装与运行

项目根目录运行：

```powershell
uv sync --locked
uv run python -m unittest discover -s tests
uv run uvicorn app.server:app --env-file .env --host 127.0.0.1 --port 8000 --reload
```

如果 Windows 尚未安装前端工具链，可使用 Scoop：

```powershell
scoop install nodejs-lts pnpm
```

另开一个 PowerShell 窗口运行前端：

```powershell
cd C:\code\shikigen-agent\frontend
pnpm install --frozen-lockfile
pnpm tauri dev
```

项目使用 `pnpm-lock.yaml` 锁定前端依赖，并在 `package.json` 中固定 pnpm 版本。
现有 Tauri 壳不会自动启动后端；生命周期管理仍按既有规划另行实现。

## 兼容性说明

- 名称为 `bash` 的工具仍使用系统默认 shell：Windows 为 cmd.exe，Unix 为 /bin/sh。工具描述会向模型明确当前平台的命令语法。
- 外部命令可能使用不同编码；无法解码的输出会使用替代字符，避免整个工具调用因此失败。这不保证所有命令的中文输出都无乱码。
- `.env` 和 `config.json` 保留；当前启用配置的数据库路径为相对路径，MCP servers 为空。
- `.shikigen/data/shikigen.db` 使用 SQLite backup API 生成一致快照；旧会话中引用的 Linux 路径不会自动迁移。
- 临时文件、历史学习记录和本地辅助配置不做批量路径替换。
