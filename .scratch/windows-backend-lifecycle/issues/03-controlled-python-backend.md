# 通过控制管道启动、使用和关闭 Python 后端

Status: ready-for-agent

## Parent

[Windows 桌面应用与后端生命周期 PRD](../PRD.md)。本票范围服从 PRD 的最终接口契约；ready-for-agent 表示信息可实施，代码仍由用户主导，助手实现需另行委托。

## What to build

测试宿主能启动真实 Python 桌面后端，读取绑定消息、检查就绪并请求正常关闭；独立 CLI 和手动 HTTP 保留自己的生命周期。此票可以使用隔离的临时数据完成验证。

**接口与设计原因：** 桌面启动器接收 --config、--startup-id、--port，持有 open_runtime()；通过 stdin/stdout 的逐行 JSON 协议控制，使用 Uvicorn Server.serve(sockets=[socket]) 与 GET /health/ready。

## Acceptance criteria

- [ ] 配置加载前显式加载项目根环境文件，python-dotenv override=False；环境文件缺失可继续，必要变量缺失报变量名，不输出密钥值。
- [ ] Python AppConfig 接受 backend 分组：port 默认 43127 且为 1～65535 整数；启动、退出期限默认 60、10 秒且为正有限数值。缺省用默认，拒绝未知字段、null、布尔值与数字字符串，错误包含字段与原因。
- [ ] 仅绑定 IPv4 127.0.0.1，使用 SO_EXCLUSIVEADDRUSE；从传入起始端口递增，占用继续、10013 记录原因后跳过、其他错误失败；到 65535 不回绕。宿主启动总期限在后续桌面接入时统一执行。
- [ ] 绑定成功发 bound，保留原 socket 交给 Uvicorn，不关闭重绑；禁用 reload。
- [ ] 耗时初始化前建立控制监听；启动器持有 runtime 上下文，HTTP 不重复装配。初始化及历史恢复完成且 HTTP 可访问后，健康响应才为 200，包含 version: 1、匹配 startup_id、status: ready；不额外请求模型生成。
- [ ] stdin 接受 shutdown，stdout 输出 bound(port) 或 startup_error(code,message)，共同字段为 version: 1、字符串 startup_id 和 type。stdout 不混入普通日志，stderr 接收日志与堆栈。
- [ ] UTF-8 逐行 JSON 以换行终止，每条最多 64 KiB，读入时限制缓冲。无效当前控制消息记录 stderr 并清理退出；可识别的旧启动消息忽略，不可解析消息不能借旧启动假设放过。
- [ ] shutdown 和仅桌面模式的 stdin EOF 能触发正常清理，停止接收新任务、关闭服务及 runtime；手动 HTTP 和 CLI 不采用此 EOF 规则。
- [ ] 用真实 Python/Uvicorn 子进程验证绑定、健康、正常退出和协议错误，使用确定性 Agent 避免模型联网；覆盖连续占用、10013、耗尽和已绑定 socket 的复用。初始化取消、持续 SSE 与卡住的宿主兜底由第 5 票补全。

## Blocked by

- [让 HTTP 应用接入外部持有的 runtime（前置重构）](01-external-runtime-http.md)

## Comments

- 2026-09-28：按用户确认的 10 票拆分发布。对应验收随本票完成，记录自动测试、Windows 原生验证与未验证项；不得将模拟进程结果代替平台验证。

