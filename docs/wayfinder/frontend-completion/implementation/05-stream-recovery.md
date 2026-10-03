# 断流后的有限 GET 恢复与手动重连

Status: ready-for-agent

实施进度：待实施

来源：[统一实施规格](../../../../.scratch/frontend-completion/PRD.md)；[公共要求与依赖总览](index.md)。

**What to build:** 意外断流后自动有限次数恢复同一运行，停止后保留手动重连和状态查询，正常等待审批或终态结束保持真实结果。

**Why:** 把观察故障与执行结果分开，提供可预测且不会重复执行的恢复路径。

**API／边界：**同 Run GET stream／纯读查询；结构化 HTTP 与 SSE error；统一读取任务、计时和 Retry-After。

**Blocked by:** [全量重建消息与当前运行事实](03-run-fact-reconstruction.md)。

## 验收条件

- [ ] 分别显示未建立、连接中、已建立、重试等待、正常结束、暂停和恢复停止；running 意外 EOF 可恢复，interrupted／终态正常 EOF 不重连，不将连接错误写成 Run error。
- [ ] 网络、GET 503／可恢复 SSE error 按 1／2／5 秒最多三次 GET；不早于 Retry-After，同一故障的 error 与 EOF 不重复安排，同目标无并发连接。
- [ ] 首帧 metadata 不重置失败计数，连续正常 30 秒或正常 interrupted／终态 回放完成才重置；三次失败后保留事实和手动入口，列表轮询不不断重开恢复。
- [ ] 手动重连、重新进入／显示和有效新租约可开启新轮次，复用任务并遵守等待；主动 Abort／失效不消耗次数或取消后台任务。
- [ ] 404、GET stream 400、GET 500、不可恢复 SSE error／解析失败停止自动恢复并提供对应手动路径；长工具无输出不按超时判失败。
- [ ] POST 错误只核实，不自动重发；保留 status／detail／Retry-After、SSE code／message／recoverable，未分类错误保留说明，不自动重启宿主。
- [ ] 以可控公开网络边界验证次数／间隔、Retry-After、metadata 后即失败、重复 EOF、失效计时器及手动竞争，并在工作台演示断流恢复。

## Comments

尚无实施或验收记录。
