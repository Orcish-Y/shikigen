---
id: windows-lifecycle-single-instance-startup-race
title: 补齐 Windows 单实例插件初始化期间的竞争保护
parent: windows-backend-lifecycle
labels: ["wayfinder:research"]
status: closed
assignee: null
blocked_by: []
resolution: 004-single-instance-startup-race.resolution.md
---

# 补齐 Windows 单实例插件初始化期间的竞争保护

## Question

第 07 票实施时检查官方插件源码发现：Windows 实现先创建命名互斥量，再创建通知窗口；另一进程如果已经看到互斥量，但 `FindWindowW` 尚未找到窗口，会继续返回插件初始化成功。

这是否意味着仅注册插件不足以满足“同时启动也只有一份后端”？在保持现有单实例插件、窗口恢复和退出契约的前提下，怎样覆盖这一段初始化竞争，并避免退出中的通知改变后端生命周期？

本票记录实施证据导致的机制补充，不改变产品行为。验证结果随[第 07 票](../../../../.scratch/windows-backend-lifecycle/issues/07-single-desktop-instance.md)交付。
