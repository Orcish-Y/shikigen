# 工具管理页面与保存接缝调查

调查日期：2026-10-13。由 inspect_tool_seams 子代理只读检查；未修改应用代码、未读取真实配置或密钥、未运行产品测试。这里记录现状，不替用户决定页面或生命周期规则。

## 页面接缝

- [App](../../../frontend/src/App.tsx) 没有页面路由，工作区固定渲染聊天；[主导航](../../../frontend/src/components/Sidebar.tsx) 已有工具入口和图标，但首项固定选中，其他项 disabled，没有页面选择回调。工具页需要新增页面选择状态与内容分支。
- [导航布局](../../../frontend/src/useNavigationLayout.ts) 和[窄屏侧栏](../../../frontend/src/components/SidebarPanel.tsx) 已有响应式基础。会话历史属于聊天工作区，不能直接成为工具页的目录。
- 现有局部 input/select/textarea 可参考；没有通用工具表单、代码编辑器、JSON Schema 编辑器或字段错误组件。
- [Overlay](../../../frontend/src/components/Overlay.tsx) 已支持原生 dialog、抽屉、Esc、外侧关闭、焦点约束和返回。工具草稿的未保存确认仍需新逻辑。
- 没有全局 Toast；已有 business-notice、role=status/alert 和局部复制反馈。新增页面可以沿用内嵌反馈。
- [ContentViewer](../../../frontend/src/components/ContentViewer.tsx) 支持完整 JSON/源码与复制。[ToolCard](../../../frontend/src/components/ToolCard.tsx) 属于聊天调用记录，新工具测试结果需要独立呈现统一执行结果。
- [后端客户端](../../../frontend/src/backend-client.ts) 已有宿主身份、AbortSignal、JSON 请求和错误处理基础；工具 CRUD、发现和测试方法尚不存在。
- [消息草稿](../../../frontend/src/message-drafts.ts) 绑定聊天与 localStorage，没有工具表单草稿、脏状态或保存冲突模型。

## 配置接缝

- [配置加载](../../../packages/harness/shikigen/app_config.py) 只有读取，没有保存 API、原子替换或并发编辑检查；其他路径、凭据与原始 JSON 接缝见[执行接缝调查](execution-baseline.md)。
- 没有 config/代码目录监视器、轮询或工具刷新入口。
- [工作目录资源](../../../packages/harness/shikigen/runtime/workspace_resources.py) 有读前后比对文件版本的模式，可借鉴冲突反馈；现有版本来自文件身份、大小、mtime，不是内容哈希，也没有覆盖工具配置和源码。
- 对应[资源测试](../../../tests/test_workspace_resources.py) 已覆盖外部修改、删除和替换；新工具保存的一致性仍需单独实现和验证。

## 结论的范围

现有导航、模态层、完整内容查看、复制与反馈样式可以复用。工具页面、schema 编辑、源码参数同步、工具草稿、配置保存、外部修改检测和测试任务管理均为新增能力，仓库现状没有预先决定这些产品规则。

## 单文件提交事实补充

同日由 inspect_tool_seams 子代理核对官方文档，用于判断保存与清理的失败边界，不代表已实现文件事务。

- 新代码使用新路径，完整写入并关闭；新配置同样先写完整临时文件，再以一次文件名替换提交 config.json。Python 的 os.replace 支持替换既有目标，跨文件系统可能失败，成功的重命名为原子操作；这个保证只覆盖一次文件替换。见 [Python os.replace](https://docs.python.org/3.12/library/os.html#os.replace)。
- Windows 的权限和打开句柄的共享模式可能使替换失败；文件被打开不一定阻止重命名，是否允许 FILE_SHARE_DELETE 是相关条件。见 [Microsoft CreateFileW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew)、[Microsoft MoveFileExW](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-movefileexw)。
- 不覆盖或提前删除旧文件、且没有其他写入者干预时，提交前失败可保留旧配置和旧代码；新代码可能留下未引用文件。提交后清理失败则是新配置已生效、旧文件残留，不能把它报告为从未保存。
- 先写代码再替换配置不构成多文件事务或断电保证。仅关闭文件/替换名称不代表全部数据和元数据已持久化；客户端未收到成功也不能证明未提交。Python flush/fsync 是另外的操作。见 [Python fsync](https://docs.python.org/3.12/library/os.html#os.fsync)。
- 文件替换本身不解决调用读取旧路径后、尚未读取源码时的竞争；完整代码取得与保存清理需要协调。已确认的执行内容固定规则仍须开发实现，不能从 os.replace 的单文件保证推导出来。
