# 通过控制管道启动、使用和关闭 Python 后端

Status: done

## Parent

[Windows 桌面应用与后端生命周期 PRD](../PRD.md)。本票范围服从 PRD 的最终接口契约；ready-for-agent 表示信息可实施，代码仍由用户主导，助手实现需另行委托。

## What to build

测试宿主能启动真实 Python 桌面后端，读取绑定消息、检查就绪并请求正常关闭；独立 CLI 和手动 HTTP 保留自己的生命周期。此票可以使用隔离的临时数据完成验证。

**接口与设计原因：** 桌面启动器接收 --config、--startup-id、--port，持有 open_runtime()；通过 stdin/stdout 的逐行 JSON 协议控制，使用 Uvicorn Server.serve(sockets=[socket]) 与 GET /health/ready。

## Acceptance criteria

- [x] 配置加载前显式加载项目根环境文件，python-dotenv override=False；环境文件缺失可继续，必要变量缺失报变量名，不输出密钥值。
- [x] Python AppConfig 接受 backend 分组：port 默认 43127 且为 1～65535 整数；启动、退出期限默认 60、10 秒且为正有限数值。缺省用默认，拒绝未知字段、null、布尔值与数字字符串，错误包含字段与原因。
- [x] 仅绑定 IPv4 127.0.0.1，使用 SO_EXCLUSIVEADDRUSE；从传入起始端口递增，占用继续、10013 记录原因后跳过、其他错误失败；到 65535 不回绕。宿主启动总期限在后续桌面接入时统一执行。
- [x] 绑定成功发 bound，保留原 socket 交给 Uvicorn，不关闭重绑；禁用 reload。
- [x] 耗时初始化前建立控制监听；启动器持有 runtime 上下文，HTTP 不重复装配。初始化及历史恢复完成且 HTTP 可访问后，健康响应才为 200，包含 version: 1、匹配 startup_id、status: ready；不额外请求模型生成。
- [x] stdin 接受 shutdown，stdout 输出 bound(port) 或 startup_error(code,message)，共同字段为 version: 1、字符串 startup_id 和 type。stdout 不混入普通日志，stderr 接收日志与堆栈。
- [x] UTF-8 逐行 JSON 以换行终止，每条最多 64 KiB，读入时限制缓冲。无效当前控制消息记录 stderr 并清理退出；可识别的旧启动消息忽略，不可解析消息不能借旧启动假设放过。
- [x] shutdown 和仅桌面模式的 stdin EOF 能触发正常清理，停止接收新任务、关闭服务及 runtime；手动 HTTP 和 CLI 不采用此 EOF 规则。
- [x] 用真实 Python/Uvicorn 子进程验证绑定、健康、正常退出和协议错误，使用确定性 Agent 避免模型联网；覆盖连续占用、10013、耗尽和已绑定 socket 的复用。初始化取消、持续 SSE 与卡住的宿主兜底由第 5 票补全。

## Blocked by

- [让 HTTP 应用接入外部持有的 runtime（前置重构）](01-external-runtime-http.md)

## Comments

- 2026-09-28：按用户确认的 10 票拆分发布。对应验收随本票完成，记录自动测试、Windows 原生验证与未验证项；不得将模拟进程结果代替平台验证。

## Implementation

- 新增 `app/desktop.py`，开发态宿主在项目根目录以虚拟环境 Python 执行
  `-m app.desktop --config <绝对路径> --startup-id <标识> --port <起始端口>`。
  通过模块位置定位根目录 `.env`，显式 `load_dotenv(..., override=False)` 后加载配置。
- `BackendConfig` 严格校验端口与期限；配置错误只保留位置与原因，抑制包含原始输入的
  Pydantic 异常链。MCP discriminator 错误使用固定原因，避免 `msg` 内嵌环境密钥。
- IPv4 listener 使用 Windows `SO_EXCLUSIVEADDRUSE`，逐端口尝试并保留成功 socket。
  `bound` 表示绑定成功；`open_runtime()` 完成初始化及历史恢复后才创建借用 runtime
  的 HTTP 应用，原 socket 交给 `Server.serve(sockets=[listener])`。
  `GET /health/ready` 返回版本、启动标识与 ready 状态，无额外模型调用。
- `app/desktop_control.py` 在初始化前建立有界读取线程，单行限制包含终止换行共
  64 KiB；无效 UTF-8、JSON、版本、命令及未终止行触发错误退出。
  拒绝 Python JSON 默认宽容接受的 NaN 等常量；可解析旧启动消息忽略。
- 协议 stdout 使用独立、不可继承的描述符，普通 stdout 重定向 stderr；真实测试
  同时验证 Python print 和工具子进程输出。控制输入使用独立无缓冲描述符，避免
  启动失败时解释器等待被读取线程占用的标准输入缓冲锁。
- shutdown/EOF 通知 Uvicorn 停止，立即开始 runtime lifecycle 清理，再等待 HTTP
  服务退出，最后由 runtime 上下文关闭数据库并释放所有权。仅桌面入口使用此协议。

## Verification

- 2026-09-30：全量测试仅在收尾运行一次，`python -m unittest discover -s tests -v`
  共 257 项，耗时 228.050 秒，256 通过、1 跳过、0 失败。
  跳过的是第 02 票的符号链接数据路径测试：本机缺少 Windows 符号链接权限。
  [完整日志](../test-results-03.log)。其中本票桌面集成测试 9 项、配置测试 24 项均通过。
- `ty check app packages/harness`、修改文件的 Ruff check/format 及 `git diff --check` 通过。
- TDD 已观察配置字段缺失、非法 JSON 常量、环境密钥回显等失败，修复后通过对应测试。
- `tests/test_desktop.py` 经真实 Windows Python/Uvicorn 子进程验证控制管道、健康检查、
  一轮确定性 Agent HTTP/SSE、shutdown、EOF、协议错误、旧启动隔离、64 KiB 边界、
  缺失换行、环境文件加载/缺失与宿主变量优先级、启动失败时 stdin 仍打开也能退出。
  `tests/desktop_process.py` 仅替换 Agent 为既有确定性 fixture，并在系统 socket
  边界注入指定故障；dotenv 测试将项目根定位到隔离临时目录，未修改真实 `.env`。
- Windows 原生验证：连续占用端口递增；运行中的服务端口不能被第二个 socket 抢占；
  保留原 socket 提供真实 HTTP 服务；普通 print 与真实子进程 stdout 均进入 stderr。
  fixture 在首次成功 bind 后禁止再次 bind，用于发现 Uvicorn 关闭重绑。
- 10013、10049 及 65535 耗尽使用 socket 边界故障注入，未声称实测 Windows 保留端口。
- 第 05 票继续覆盖初始化取消、持续 SSE 退出与卡住时宿主强制回收；本票没有实现宿主
  启动/退出总期限、Windows Job、桌面 UI，也未验收 macOS。
- code-review：Standards 0 项；Spec 初次发现 discriminator 错误密钥回显 1 项，
  修复并复核后剩余 0 项。未暂存或提交 Git。
- 接口依据：[Uvicorn 程序化运行](https://www.uvicorn.org/#running-programmatically)、
  [Windows SO_EXCLUSIVEADDRUSE](https://learn.microsoft.com/en-gb/windows/win32/winsock/so-exclusiveaddruse)，
  并核对本机已安装 Uvicorn 的 `server.py` socket 接入与清理顺序。
