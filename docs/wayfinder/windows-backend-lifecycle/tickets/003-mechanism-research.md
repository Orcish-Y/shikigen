---
id: windows-lifecycle-mechanism-research
title: 验证后端托管与数据独占的底层机制
parent: windows-backend-lifecycle
labels: ["wayfinder:research"]
status: closed
assignee: null
blocked_by: []
resolution: 003-mechanism-research.resolution.md
---

# 验证后端托管与数据独占的底层机制

## Question

在[托管接口讨论记录](../../../archive/README.md#windows-历史与验收)已确认的行为下，哪些具体 API、调用顺序和失败处理能支撑 Windows 后端托管，并为未来 macOS 保留一致接口？

需要使用官方文档、上游源码和本地版本信息回答以下技术问题：

- Windows 创建进程和纳入 Job 的顺序如何覆盖宿主在任意启动阶段崩溃的情况？仅挂起创建后再 Assign 是否仍有未归属的残留窗口，是否需要创建时关联 Job？句柄继承、异常分支和进程树回收完成如何处理？
- Python 绑定并保留 socket 后如何交给当前 Uvicorn 使用？Windows 的独占绑定、端口占用与系统保留端口等错误应如何分类？
- stdin 控制监听怎样在初始化阶段生效？如何协调 Uvicorn 的连接等待、SSE 和 runtime 清理，避免尚未进入 lifespan 清理就耗尽退出期限？
- 哪种跨平台锁可用于共享 open_runtime() 入口？如何在数据库恢复前取得锁，在正常关闭后释放，并在进程强杀后不遗留逻辑死锁？聊天库与 checkpoint 路径不同或部分重叠时锁哪些资源？
- 上述事实对公共平台接口、退出确认及超时契约有什么约束？macOS 的具体进程托管实现仍不在本票范围内。

完成标准：形成带一手来源及版本信息的 Markdown 调查资产，区分文档或源码可确认的事实、建议方案及仍需 Windows 实测的验收项。报告链接作为本票 resolution 的资产。此票不执行产品实现，不代替用户决定产品行为，也不将源码分析表述为已完成运行验证。
