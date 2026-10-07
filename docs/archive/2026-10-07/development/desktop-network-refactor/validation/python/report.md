> 归档于 2026-10-07；正文状态与命令属于原开发阶段。当前完成情况见 [开发交接](../../../../../../development-handoff.md)。相对路径链接已迁移；代码块中的旧 scratch 路径需按归档路径调整。

# Python 验证报告：桌面端口整理

- 执行模型：gpt-6-luna，推理强度 max。
- 工作目录：`C:\code\shikigen-agent`。
- 验证日期：2026-10-07（Asia/Shanghai）。
- 范围：桌面监听器、配置加载、桌面启动与 CORS、生命周期清理、HTTP 服务回归、包导入；指定的 Ruff lint/format 与 ty 检查。
- 未操作 Git，未读取用户 `config.json` 或环境密钥；没有启动付费模型或 MCP 服务。

## 结果

六组 unittest 共 **69 项通过、0 项失败、0 项跳过**。`test_app_config` 的共享夹具测试遍历全部 **34 个唯一案例**（6 个有效配置、28 个无效配置），每个案例都通过真实 `load_app_config` 执行。桌面网络测试在主 agent 修复 lint 后又单独复跑，7 项全部通过。

| 命令 | 退出码 | 结果 |
|---|---:|---|
| `.venv/Scripts/python.exe -X utf8 -m unittest discover -s tests -p test_desktop_network.py -v` | 0 | 7 项通过；初次专项 |
| `.venv/Scripts/python.exe -X utf8 -m unittest discover -s tests -p test_app_config.py -v` | 0 | 24 项通过；其中遍历全部 34 个共享配置案例 |
| `.venv/Scripts/python.exe -X utf8 -m unittest discover -s tests -p test_desktop.py -v` | 0 | 16 项通过 |
| `.venv/Scripts/python.exe -X utf8 -m unittest discover -s tests -p test_desktop_lifecycle.py -v` | 0 | 3 项通过 |
| `.venv/Scripts/python.exe -X utf8 -m unittest discover -s tests -p test_server.py -v` | 0 | 17 项通过 |
| `.venv/Scripts/python.exe -X utf8 -m unittest discover -s tests -p test_package_imports.py -v` | 0 | 2 项通过 |
| `.venv/Scripts/ruff.exe check app/desktop.py app/desktop_network.py packages/harness/shikigen/app_config.py tests/test_app_config.py tests/test_desktop.py tests/test_desktop_lifecycle.py tests/test_desktop_network.py` | 初次 1；修复后 0 | 初次发现两处 B905；主 agent 在 `tests/test_desktop_network.py` 两个 `zip()` 调用添加 `strict=True` 后，同范围 lint 通过 |
| `.venv/Scripts/ruff.exe format --check app/desktop.py app/desktop_network.py packages/harness/shikigen/app_config.py tests/test_app_config.py tests/test_desktop.py tests/test_desktop_lifecycle.py tests/test_desktop_network.py` | 初次 0；修复后 0 | 两次均通过，7 个文件均已格式化 |
| `.venv/Scripts/ty.exe check app packages/harness/shikigen` | 0 | All checks passed |
| `.venv/Scripts/python.exe -X utf8 -m unittest discover -s tests -p test_desktop_network.py -v`（修复后复跑） | 0 | 7 项通过 |

各测试集首次运行合计 69 项通过；修复后网络专项另复跑 7 项通过。所有已运行测试均无失败或跳过。主 agent 对 lint 的修复未改动断言或产品代码。未重复全仓长回归（审批逻辑不在本次改动范围）。

## 初次 lint 失败与修复后复验

初次 Ruff 输出指出 `tests/test_desktop_network.py:20` 和 `:95` 的 `zip()` 未指定 `strict=`。主 agent 为两个配对调用补充 `strict=True`。初次的原始失败仍保存在 [`ruff_check.stdout.log`（原始产物已删除）](../../../../README.md#已删除的材料)；精确命令和退出码在同名 command/exitcode 日志。修复后专项及 Ruff 检查日志分别为：

- [`test_desktop_network_postfix.stderr.log`（原始产物已删除）](../../../../README.md#已删除的材料)；
- [`ruff_check_postfix.stdout.log`（原始产物已删除）](../../../../README.md#已删除的材料)；
- [`ruff_format_postfix.stdout.log`（原始产物已删除）](../../../../README.md#已删除的材料)。

每次命令均分别保存 stdout、stderr、精确命令和退出码于 [`logs/`（原始产物已删除）](../../../../README.md#已删除的材料)；unittest 详细清单位于 stderr 日志。

## 文件完整性

共对 9 个受影响文件记录 SHA-256。初始验证前后（主 agent lint 修补前）**9/9 哈希一致**，证明本验证 agent 没有修改产品、测试、夹具或文档。随后主 agent 的 B905 修补只改变 `tests/test_desktop_network.py`；最终快照与基线相比 **8/9 相同，1/9 按预期不同**。修补后该文件 SHA-256 为 `0A9617908300A02045F7B52912BA5B2665274B7AC16E0CC686B86FBEF48A37D8`，且已重跑专项、Ruff lint 与格式检查。

- 基线：[`hashes-before.json`（原始产物已删除）](../../../../README.md#已删除的材料)
- 初轮验证后：[`hashes-after.json`（原始产物已删除）](../../../../README.md#已删除的材料)
- 主 agent 修补后最终：[`hashes-final.json`（原始产物已删除）](../../../../README.md#已删除的材料)

## 未覆盖范围

本报告只覆盖 Python 端；Rust 端验证由并行工作单独负责。没有运行完整仓库长回归，也没有进行 Windows GUI/真实桌面实机验收。指定 Python 测试、ruff 修复后 lint/format 与 ty 检查均通过。
