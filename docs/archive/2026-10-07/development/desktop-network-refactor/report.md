> 归档于 2026-10-07；正文状态与命令属于原开发阶段。当前完成情况见 [开发交接](../../../../development-handoff.md)。相对路径链接已迁移；代码块中的旧 scratch 路径需按归档路径调整。

# 桌面端口语义与网络模块整理

日期：2026-10-07。用户授权按已讨论方案实现；主 agent 负责代码和修复，两个 `gpt-6-luna / max` 子 agent 负责最终 Python 与 Rust 验证。未执行 Git 操作。

## 实现

- 新增 [app/desktop_network.py](../../../../../app/desktop_network.py)，承接原桌面入口中的 `bind_listener()` 和 `get_desktop_frontend_origins()`。保留成功绑定的 socket、Windows 独占监听、占用及 10013 回退、其他错误传播和精确 CORS 来源策略。
- [app/desktop.py](../../../../../app/desktop.py) 专注生命周期编排。运行参数和 argparse 内部名称使用 `start_port`，成功绑定后使用 `bound_port` 并上报实际端口。
- [Rust 后端配置](../../../../../frontend/src-tauri/src/backend.rs) 的内部字段改为 `start_port`；[宿主管理器](../../../../../frontend/src-tauri/src/backend/manager.rs) 使用它传递起点，接收控制消息后使用 `bound_port`。解析器同时修正了局部配置对象及错误回调的命名。
- 外部 `config.json` 的 `backend.port`、Python 配置模型字段 `port`、CLI `--port` 和控制消息 `bound.port` 保持既有格式；配置与 CLI 表示起始端口，控制消息表示实际绑定结果。起始默认值仍为 43127。
- 新增共享 [配置验收样例](../../../../../tests/fixtures/desktop_backend_config_cases.json)：34 个案例（6 有效、28 无效）。[Python 配置测试](../../../../../tests/test_app_config.py) 通过实际配置加载入口执行，[Rust 配置测试](../../../../../frontend/src-tauri/tests/backend_config.rs) 编译包含并遍历相同文件。覆盖默认值、部分配置、端口上下界、期限、非法类型、未知字段、非有限数值和错误信息不回显非法输入。
- 新增 [监听器专项测试](../../../../../tests/test_desktop_network.py)，更新既有桌面与生命周期测试的模块导入，修正 [配置模型注释](../../../../../packages/harness/shikigen/app_config.py) 和 [Windows 生命周期说明](../../../../windows-backend-lifecycle.md)。

## 验证

| 范围 | 最终结果 | 证据 |
| --- | --- | --- |
| Python 相关完整回归 | 69 通过、0 失败、0 跳过：监听器 7、配置 24、桌面 16、生命周期 3、HTTP 17、包导入 2 | [Python 报告](validation/python/report.md) |
| Python 共享案例 | 34/34 验收案例全部执行并通过 | [配置测试日志（原始产物已删除）](../../README.md#已删除的材料) |
| Rust 配置专项 | 3 通过、0 失败、0 忽略；包含共享案例 34/34 | [专项原始日志（原始产物已删除）](../../README.md#已删除的材料) |
| Rust 完整回归 | 36 通过、0 失败、0 忽略；包含配置、日志、manager、retry、shutdown、managed_process、网页打开与工作区文件打开 | [Rust 报告](validation/rust/report.md)、[全套原始日志（原始产物已删除）](../../README.md#已删除的材料) |
| Node 启动协调器 | 9 通过、0 失败、0 跳过 | [原始日志（原始产物已删除）](../../README.md#已删除的材料) |
| Ruff、Python 格式、ty | 指定范围最终全部退出 0 | [Python 命令与结果](validation/python/report.md) |
| Rust 格式 | 修改的三个 Rust 文件检查退出 0 | [Rust 命令与结果](validation/rust/report.md) |

69 和 36 为各自完整相关回归中的测试数量；共享案例位于单个测试的循环内，不额外加到测试总数。Rust 专项已包含在完整 Rust 回归中，不重复累计。主 agent 已核对子 agent 报告、原始结果、退出码和最终源码哈希。

## 验证过程与范围

初次 Ruff 报告新监听测试两处 `zip` 缺少 `strict=`。主 agent 改为明确的等长配对并添加 `strict=True`，随后重跑监听器 7 项、同范围 Ruff 和格式检查，均通过；初次 lint 失败日志保留。产品代码、断言和其他测试均未因该修复而变化，其余已通过检查未重复。

初次 Cargo 在原构建目录无法覆盖 `shikigen-desktop.exe`，退出 101，尚未执行测试。验证 agent 只读观察确认原应用 PID 10548 运行于该路径，未停止它。缓存复制阶段只读源目录，排除主可执行文件；Robocopy 退出 1 表示已复制文件。最终两条 Cargo 命令使用独立 `--target-dir`，均退出 0。原始阻塞记录没有计为通过，也没有声称首次 Cargo 对整个原构建缓存完全无写入。

本轮运行了影响范围内的完整 Python 回归和完整 Rust 回归，没有重复此前耗时较长的全仓 Python 回归，也没有运行实际 WebView/HMR 或人工原生窗口验收。Node 专项使用依赖注入的 CLI 回调及真实 Vite 监听，没有复跑真实 Tauri CLI。此前全仓 Python 的审批恢复 3 秒超时和 Windows 符号链接权限跳过，仍见[上轮验证记录](../dev-port-fallback/report.md)，未被本轮相关测试通过结果覆盖。未使用用户配置、数据库或付费模型调用。隔离 Cargo 输出和测试原始证据保存在本任务的验证目录。
