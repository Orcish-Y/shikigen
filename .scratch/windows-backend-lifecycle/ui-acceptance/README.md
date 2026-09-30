# 第 04 票：真实 Tauri 窗口验收

日期：2026-09-30。结果：通过。

使用实际 `shikigen-desktop.exe`、项目 Windows 虚拟环境与当前配置；宿主从项目根目录以外的 cwd 启动。前端使用重新构建的 `frontend/dist`，通过独立本地 HTTP 服务提供；页面运行在 Tauri WebView2 内，并使用真实 Tauri IPC。没有注入假状态或替换后端 Agent。

| 验收行为 | 结果 |
| --- | --- |
| 启动期间 | starting，revision 1，无地址；页面显示启动提示。 |
| 后端就绪 | ready，revision 2；实际健康响应的 startup_id 匹配；顶部、侧栏和编辑器文字一致。 |
| 连续刷新三次 | startup_id、revision、Python 进程列表均保持不变；重新显示就绪。 |
| 第二个宿主争用同一数据 | 显示 RuntimeDataInUse 原始原因；base_url 为空，can_retry 为 false；已有实例仍健康。 |
| 关闭失败窗口 | 只向真实 Tauri 主窗口发送 WM_CLOSE，宿主正常退出，退出码 0。 |
| 关闭就绪窗口 | 宿主正常退出，退出码 0；保留的 Python 进程句柄确认退出。 |
| 只强杀真实 Tauri 宿主 | 使用 TerminateProcess 单独杀宿主；所有本次 Python 句柄确认退出；外部独立 HTTP 服务仍返回 200。 |

证据：[结构化结果](results.json)、[完整日志](../test-results-04-ui.log)。

截图：[启动提示](00-starting-9237.png)、[后端就绪](01-ready.png)、[三次刷新后](02-after-refresh.png)、[数据占用错误](03-data-in-use.png)、[正常退出后再次打开](04-reopened.png)。

验收发现并修复顶部与两处旧连接标签不一致；仅统一状态展示，当前会话仍是界面预览，发送按钮未接入业务请求。该能力属于第 09 票。

验收脚本曾向框架内部的 Tao Thread Event Target 也发送 WM_CLOSE，导致假失败；定位后限定为用户可见的 Tauri Window。进程归属检查同时校验创建时间，避免已复用的父 PID 把孤儿进程误认成后代。最终结果来自修正后的完整验收。

复现：先 `pnpm build` 并 `cargo build --bin shikigen-desktop --offline`，确保 5173、9237～9239 空闲，随后在项目根目录运行 `.venv/Scripts/python.exe .scratch/windows-backend-lifecycle/acceptance_ui.py`。脚本会打开真实桌面窗口、创建第二个宿主触发占用错误、刷新三次、关闭窗口、单独强杀测试宿主，并清理自行启动的进程。原生工具后代与普通 HTTP 入口竞争的独立验收见同票已有 Windows 原生测试记录。

调试配置只加入本次启动的进程环境，未修改注册表或系统配置；[Microsoft WebView2 调试接口说明](https://learn.microsoft.com/en-us/microsoft-edge/webview2/how-to/debug-visual-studio-code)。临时 WebView 数据目录已清理，保留脚本、日志和截图。
