---
id: windows-backend-lifecycle
title: Windows 桌面应用与后端生命周期决策地图
labels: ["wayfinder:map"]
status: closed
---

# Windows 桌面应用与后端生命周期决策地图

## Destination

明确 Windows 原生 Tauri 单实例应用托管 Python 后端的启动、就绪、关窗后托盘驻留、显式退出、异常回收和手动重试方案，形成可交给实现者的接口约定与验收标准。
地图完成意味着实现前的决策已明确，不代表功能已经实现。
进程托管接口需隔离平台差异，为未来 macOS 实现预留替换位置。

## Notes

- 使用本目录的本地 Markdown tracker；规则见 [tracker 说明](tracker.md)。
- 按 wayfinder 进行规划；讨论决策时使用 grilling、domain-modeling，设计可替换模块接口时使用 codebase-design。用户主导代码实现，未授权修改 Git。
- [实施规划](../../windows-backend-lifecycle-plan.md)保留架构草案、实施顺序和验收场景；已定决策以票据的 resolution 为准，候选技术细节不等于已确认结论。
- 每次只处理一张决策票据；未关闭、无未完成依赖、未被认领的子票据构成当前 frontier。开放票据不在地图正文重复列出。
- 用户逐项确认的单实例、托盘驻留、动态端口及平台适配规则已汇总到[最终接口契约](tickets/002-runtime-contract.resolution.md)；[讨论记录](tickets/002-runtime-contract.discussion.md)保留历史过程。
- 地图已完成：已知范围内的决策均已解决，下一阶段按最终契约实施。此状态不表示应用功能或平台行为验证完成。

## Decisions so far

- [确定平台、生命周期归属与故障行为](tickets/001-behavior.md) — Windows 优先，Tauri 拥有后端及所属进程树，正常退出先清理，异常退出回收，失败后手动重试。
- [验证后端托管与数据独占的底层机制](tickets/003-mechanism-research.md) — 已核实创建时关联 Job、保留 socket、初始化与 SSE 清理协调及原生数据锁的机制依据，列明接口约束和待实施验收项。
- [确定 Windows 后端托管接口与状态转换](tickets/002-runtime-contract.md) — 已确认启动、协议、状态、托盘、回收、数据独占及 macOS 替换接口，形成最终契约与实现验收清单。

## Not yet specified

当前范围内没有尚待确认的产品行为或接口职责。具体实现类型、文件组织及平台验证按最终契约推进；后续新增需求或实现证据推翻前提时，再创建对应决策票据。

## Out of scope

- 本地图不执行代码实现或 Windows 环境迁移。
- macOS 的具体实现与平台验证、安装包和 Python 运行时分发留待后续；预留 macOS 可替换接口属于本轮范围，需覆盖启动及进程回收能力。
- 后端自动重启不属于本版行为。
- 渲染进程独立崩溃后的页面恢复策略不在本轮宿主进程生命周期方案内。
