# Triage Labels

本地 Markdown tracker 使用 `Status:` 字段记录 triage 状态。

| 工程技能角色 | 本地状态值 | 含义 |
| --- | --- | --- |
| `needs-triage` | `needs-triage` | 等待维护者评估 |
| `needs-info` | `needs-info` | 等待报告者补充信息 |
| `ready-for-agent` | `ready-for-agent` | 信息完整，可交给 agent 独立处理 |
| `ready-for-human` | `ready-for-human` | 需要人工实现 |
| `wontfix` | `wontfix` | 决定不处理 |
| 额外完成状态 | `done` | 工作已完成；它不是待分流角色 |

Wayfinder 地图和子票据有各自的 `open`、`closed`、`claimed`、`resolved` 状态；不要把这些状态改写成 triage 状态。
