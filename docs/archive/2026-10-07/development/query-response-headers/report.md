> 归档于 2026-10-07；正文状态与命令属于原开发阶段。当前完成情况见 [开发交接](../../../../development-handoff.md)。相对路径链接已迁移；代码块中的旧 scratch 路径需按归档路径调整。

# 查询响应头抽离验证报告

- 执行模型：`gpt-6-luna`，推理强度 `max`，派发时显式指定。
- 工作目录：`C:\code\shikigen-agent`。
- 验证版本：`query_response_policy` 已按每次响应复制 `_QUERY_RESPONSE_HEADERS`，全部验证在该最终调整之后执行。
- 范围：三个相关 HTTP 套件，以及 `app/routes/queries.py`、`app/server.py` 的 Ruff check／format check 和 ty check。
- 主 agent 已核对原始测试摘要、静态检查日志及测试 agent 报告；未操作 Git。

## HTTP 测试套件

全部命令从仓库根目录串行执行，每个进程退出码为 `0`。共 24 项通过、0 失败、0 错误、0 跳过。

| 命令 | 退出码 | 结果 | 原始 stdout | 原始 stderr |
|---|---:|---|---|---|
| `.venv/Scripts/python.exe -X utf8 -m unittest discover -s tests -p test_conversation_queries.py -v` | 0 | 4 通过、0 失败／跳过；12.204s | [stdout（原始产物已删除）](../../README.md#已删除的材料) | [stderr（原始产物已删除）](../../README.md#已删除的材料) |
| `.venv/Scripts/python.exe -X utf8 -m unittest discover -s tests -p test_thread_pagination.py -v` | 0 | 12 通过、0 失败／跳过；24.762s | [stdout（原始产物已删除）](../../README.md#已删除的材料) | [stderr（原始产物已删除）](../../README.md#已删除的材料) |
| `.venv/Scripts/python.exe -X utf8 -m unittest discover -s tests -p test_workspace_resources.py -v` | 0 | 8 通过、0 失败／跳过；6.676s | [stdout（原始产物已删除）](../../README.md#已删除的材料) | [stderr（原始产物已删除）](../../README.md#已删除的材料) |

unittest 的详细摘要输出到 stderr。会话查询和分页日志中的存储损坏／繁忙 traceback 来自预期故障注入，套件最终均为 `OK`。

## 静态检查

全部从 `C:\code\shikigen-agent` 执行，每个退出码为 `0`。

| 命令 | 结果 | 原始 stdout | 原始 stderr |
|---|---|---|---|
| `.venv/Scripts/ruff.exe check app/routes/queries.py app/server.py` | `All checks passed!` | [stdout（原始产物已删除）](../../README.md#已删除的材料) | [stderr（原始产物已删除）](../../README.md#已删除的材料) |
| `.venv/Scripts/ruff.exe format --check app/routes/queries.py app/server.py` | `2 files already formatted` | [stdout（原始产物已删除）](../../README.md#已删除的材料) | [stderr（原始产物已删除）](../../README.md#已删除的材料) |
| `.venv/Scripts/ty.exe check app/routes/queries.py app/server.py` | `All checks passed!` | [stdout（原始产物已删除）](../../README.md#已删除的材料) | [stderr（原始产物已删除）](../../README.md#已删除的材料) |

本次只做受影响的定向验证，没有重跑完整后端、前端或 Rust，也没有启动 GUI、访问网络或操作既有服务／端口。上述检查未执行，不计作通过。
