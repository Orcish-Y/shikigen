---
id: windows-lifecycle-runtime-contract
title: 确定 Windows 后端托管接口与状态转换
parent: windows-backend-lifecycle
labels: ["wayfinder:grilling"]
status: closed
assignee: null
resolution: 002-runtime-contract.resolution.md
blocked_by: [windows-lifecycle-behavior, windows-lifecycle-mechanism-research]
---

# 确定 Windows 后端托管接口与状态转换

## Question

在已确认的行为范围内，Tauri 壳、Python 后端和页面之间采用什么接口与状态转换，才能可靠地启动、判断就绪、停止和重试？

需要明确：

- 在已确认关闭 Uvicorn reload 的前提下，开发态 Python 路径、工作目录、配置与端口如何确定？
- 在配置起始端口、占用后递增尝试的行为下，如何以实际绑定结果处理竞争，以及将本次后端监听地址传给 React 的 HTTP/SSE 客户端？如何落实单实例与重复启动唤起已有窗口，并避免独立入口的后端同时恢复同一份运行数据？
- 健康检查如何表达就绪，如何识别本次启动的后端而非已有服务？
- 正常关闭使用哪一种控制通道，如何进入已有 runtime 清理流程？
- Job 句柄如何归属与继承，如何避免纳入 Job 前后端已创建子进程的竞态，以及失败时如何回收？
- 公共生命周期逻辑与平台进程托管之间采用什么可替换接口，使未来 macOS 实现可接入，而 React、控制协议和公共状态转换保持一致？
- 启动、退出和异常回收的时间上限分别是什么？
- 重试、显式退出和启动完成并发发生时，谁负责串行化状态变化？关闭窗口仅隐藏到托盘时，如何保持同一后端并恢复窗口？
- 托盘菜单如何触发受控退出，后台失败如何提示用户，托盘创建失败时如何处理？
- 页面如何获取状态、错误及启动日志，如何发起手动重试？

完成标准：记录选定接口、状态转换、失败处理、时间上限及选择原因，使实现者不必自行猜测产品行为。遇到需要外部技术调查的问题时，再创建对应研究票据与依赖，不以未经验证的猜测关闭本票据。

上下文：[实施规划](../../../windows-backend-lifecycle.md)。

最终结论：[托管接口与状态转换契约](002-runtime-contract.resolution.md)。

历史讨论：[逐项确认记录](../../../archive/README.md#windows-历史与验收)。以最终契约为实施依据。

底层技术依据由[验证后端托管与数据独占的底层机制](003-mechanism-research.md)补齐，见[研究结论](003-mechanism-research.resolution.md)。本票已汇总确认的接口、状态转换、失败处理、期限及验收项；关闭表示决策完成，不表示代码实现或平台验证完成。
