# 工具库验证与报告入口

整理于 2026-10-23。本页索引已有证据与可复用的验证方式，本次文档整理没有重新运行产品测试。测试数字属于各自代码阶段，不能相加为当前版本的全仓结论。

## 按改动选择验证范围

| 改动 | 后端入口 | 页面与公开交互入口 |
| --- | --- | --- |
| 定义、保存、草稿与名称 | `tests/test_tool_library_api.py`、`test_tool_config_lifecycle.py` | `frontend/tests/tool-library.test.mjs`、`tool-management-dom.test.mjs` |
| HTTP 映射、schema 与认证 | `tests/test_tool_execution.py`、`test_tool_library_api.py` | 工具页面 DOM、实际 rjsf 输入与 JSON 切换 |
| Python 源码与结构同步 | `tests/test_python_tool_api.py`、`test_tool_execution.py`、`tests/fixtures/python_source_cases.json` | `frontend/tests/python-source.test.mjs`、工具页面 DOM |
| MCP 两种传输与发现 | `tests/test_mcp_tool_api.py`、`test_mcp_http_api.py` | `frontend/tests/mcp-management-dom.test.mjs` |
| OpenAPI 解析与批量保存 | `tests/test_openapi_import_api.py` | `frontend/tests/openapi-import-dom.test.mjs` |
| 测试取消、超时与关闭 | `tests/test_tool_test_lifecycle_api.py`、`test_sync_tools.py` | 工具页面 DOM 的启动、取消、离开与结果不确定场景 |
| 消费者、同步调用与装配 | `tests/test_tool_consumers.py`、`test_sync_tools.py`；装配变更再检查 runtime、agent_factory、tool_registry 等相关文件 | schema／完整结果展示发生变化时检查工具页 |

后端主要通过公开 HTTP API 和公开工具调用验证，使用临时配置、本地可控 HTTP／MCP 服务和真实 Python 子进程。输入错误应在业务操作前失败，取消／超时应观察实际资源清理。页面验证操作真实组件和业务状态，涉及布局的改动再做原生窗口验收。

## 常用命令

在仓库根目录运行相关工具调用专项：

```powershell
.venv\Scripts\python.exe -m unittest tests.test_sync_tools tests.test_tool_consumers -q
.venv\Scripts\ty.exe check packages/harness/shikigen app
git diff --check
```

完整后端以及引用同目录 fixture 的 runtime 测试使用 discovery，保持项目现有导入路径：

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -q
.venv\Scripts\python.exe -m unittest discover -s tests -p test_runtime.py -q
```

前端完整测试及生产构建使用项目脚本：

```powershell
pnpm -C frontend test
pnpm -C frontend build
```

Ruff 检查和格式检查限定本次修改的 Python 文件。Windows 真实 WebView 验收入口为 [tool_library_acceptance.py](../../../frontend/src-tauri/tests/tool_library_acceptance.py)，使用项目正式前端构建、受控后端和本地服务；环境准备沿用[Windows 开发说明](../../windows-development.md)。需要报告布局、焦点或滚动行为时记录实际视口与观察范围。

## 已有结果及其边界

| 阶段 | 已记录结果 | 详细报告 |
| --- | --- | --- |
| 14 消费者复用 | 后端 474 项：473 通过、1 跳过；最终前端 393 项通过；原生稳定 ID／schema 场景通过 | [14 验收与审查](stable-id-consumer-reuse.review.md) |
| 同步调用补充 | 后端 487 项：486 通过、1 跳过；保留全量耗时和日志位置 | [同步调用记录](stable-id-consumer-reuse.md#验证入口) |
| 工具库目录迁移 | 相关实际用例 184 项通过；首轮 fixture 导入命令有误，补跑 discovery 成功 | [模块布局与迁移验证](tool-module-layout.md) |
| `c42a50f` 提交前复核 | 最终同步专项 15 项通过；修改文件 Ruff／格式、后端源码 ty 和 diff 检查通过 | `tests/test_sync_tools.py`；不是一次新的完整后端回归 |

## 主题报告

- MCP：[Streamable HTTP](mcp-streamable-http.review.md)、[发现生命周期](mcp-discovery-lifecycle.review.md)。
- OpenAPI：[基础导入](openapi-basic-import.review.md)、[兼容与认证](openapi-compatibility-auth.review.md)。
- 公共生命周期：[测试取消](test-cancellation-lifecycle.review.md)、[配置冲突与快照](config-conflicts-call-snapshot.review.md)、[稳定 ID 复用](stable-id-consumer-reuse.review.md)。
- 01–07 的验证结果随[实施票据](implementation/index.md)及对应主题实现记录保存，没有为缺少独立 review 文件的阶段补造审查结论。

这些报告保留当时的失败、修复、重跑和未覆盖范围。阶段报告内“尚未完成后续票”的文字描述的是当时状态；当前能力和延期目标由[开发指南](README.md)及各主题记录汇总。

## 原始证据位置

本机日志保留在 `.scratch/tools-workflow/`，原生截图在 `verification/native/`，认证简化专项在 `verification/ticket04/`，编辑器选型探针在 `research/python-parser/` 与 `research/python-storage/`。它们受 Git 忽略，新的 checkout 以本目录的实现和审查报告理解结论，需要新的证据时运行现存测试生成。

整理范围和历史规格见[归档说明](../../archive/2026-10-23/tools-workflow/README.md)。临时探针中的 `node_modules`、构建缓存和临时配置属于本机实验环境，不能充当项目依赖或产品交付记录。
