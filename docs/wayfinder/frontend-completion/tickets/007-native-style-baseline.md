---
id: frontend-native-style-baseline
title: 复核当前 Tauri 界面的视觉基准
parent: frontend-completion
labels: ["wayfinder:task"]
mode: HITL
status: closed
assignee: codex
blocked_by: []
resolution: 007-native-style-baseline.resolution.md
---

# 复核当前 Tauri 界面的视觉基准

## Question

以用户指定的设计原稿为目标，通过当前 frontend/ Tauri 窗口或用户提供的原生截图核对实际页面，记录影响新组件设计的差异，能否确认首版样式基准？

**做什么：**读取两份 HTML 原稿及用户提供的项目截图，核对桌面展开／收起的颜色、字体、内容区比例和当前差异，确认实施前样式基准；其他视口、弹层、宿主页与滚动／焦点登记为实施后验收项。

**为什么：**用户明确要求尽量贴近原稿。HTML 布局、系统缩放与原生窗口装饰需要正确换算；项目截图可以说明当前外观，其他视口与操作行为还需要实际证据，新增组件才能可靠延续原稿比例。

**使用入口：**frontend 的 pnpm tauri dev 或可用现有原生应用，保留宿主后端所有权与动态地址；样式依据 [design.md](../../../../frontend/design.md)。浏览器 preview 没有 Tauri 宿主和真实业务状态，不能替代原生状态核对。

**工作边界：**此票据取得当前视觉证据以支持设计决定，不提交消息、批准工具、修改配置或实现页面。用户于 2026-10-03 明确确认“定稿基准，实机验收后置”，将原要求的完整实机前置检查改为实施后验收；证据缺项如实保留，票据关闭不表示未观测项目通过。

## 进展与证据

2026-10-03 已读取用户指定的两份 HTML 原稿并查看项目展开／收起两张原生截图，完成桌面两态的静态对照。design.md 已更新为以原稿为视觉目标，并记录尺寸换算、当前偏差与新组件继承要求。其他视口、覆盖层、宿主页以及滚动和焦点仍待取得证据；直接原生控制 API 仍不可用。

取证结果、原稿差异和剩余验收项见[视觉基准复核记录](007-native-style-baseline.evidence.md)，真实交流见[进展与交流](007-native-style-baseline.discussion.md)。用户已确认[视觉基准收尾安排](007-native-style-baseline.review.md)，本票据按调整后的规划范围关闭；结论与验收责任见[决议](007-native-style-baseline.resolution.md)。
