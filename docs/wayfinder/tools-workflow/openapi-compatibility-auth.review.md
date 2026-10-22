# 11 号票审查与验证

2026-10-22。规格：`.scratch/tools-workflow/issues/11-openapi-compatibility-auth.md`，关联[首版决议](tickets/005-openapi-import-scope.resolution.md)。实现和认证范围见[实现记录](openapi-compatibility-auth.md)。隐藏机制按用户此前调整留待统一设计。

基准为开发开始前的 `e6fcdb01e4e67abf82ecac45979bf0b665f3cf6c`。审查命令为 `git diff e6fcdb01e4e67abf82ecac45979bf0b665f3cf6c --`，包括已暂存的新文件；审查时尚无新增提交，提交范围为空。由 code-review 技能要求的两个独立审查 Agent 分别检查规范与规格。

## Standards

最终复核：0 项文档规范违反，0 项剩余 smell 建议。目录归属、依赖方向、直接认证值、rjsf 配置及页面布局符合现有规范。

初审有 1 项低优先级 possible Duplicated Code：成功路径重复构造来源快照。已保留首次构造，后续仅补 servers，复核确认解决。

## Spec

最终复核：0 项未解决发现。

初审有 2 项 P2：内部引用的 null 分支未先解析、显式官方默认方言被误认为自定义。均先通过公开 API 回归复现，再修正并复核。null 两分支引用、约束保留、循环诊断和重叠 oneOf 拒绝均通过验证。

另补充输出结构不可用时只留空解释的回归：无效输出方言不能阻断受支持请求。

## 验证证据

- 后端全量 `python -m unittest discover -s tests`：442 项，441 通过、1 跳过，577.326 秒。日志 `.scratch/tools-workflow/11-backend-full.log`。该轮开始后审查补入两项 API 回归；最终针对整个 OpenAPI API 文件重跑 13 项全部通过，14.151 秒，日志 `11-api-final.log`。
- 前端全量：383 项全部通过，81.919 秒，日志 `11-frontend-full.log`。其中 OpenAPI 交互 5 项覆盖方案切换、补齐组合认证、删绑定阻止保存、取消缺配置项、来源查看及现有保存恢复。
- TypeScript、ty、相关 Python 文件 Ruff 与格式检查通过。生产 Vite 构建通过，57.09 秒，日志 `11-build.log`；保留已有的大 chunk 提示。
- 真实 Windows Tauri 验收 `test_openapi_upload_paste_configure_edit_and_execute` 最终通过，7.961 秒，日志 `11-native-final.log`。上传 JSON、内部 parameter 引用、未支持接口隔离、来源认证方案、组合密钥补齐、普通详情编辑和真实认证请求、粘贴 YAML 再导入均验证通过；解析／预览／保存没有调用业务接口。
- 已检查 1440px／390px 预览及认证字段截图：64px 导航、256px 侧栏、48px 操作栏、7:5 双栏与窄屏堆叠保持；保存按钮可见、无横向溢出、滚动后密码字段可操作。截图位于 `.scratch/tools-workflow/verification/native/test_openapi_upload_paste_configure_edit_and_execute/openapi-auth-preview-*.png` 与 `openapi-auth-fields-*.png`。
- `git diff --check` 通过。新增文档链接已核对；原有前端规范中的历史截图路径未改动。

两轴结论分别为 Standards 0、Spec 0，无未解决的审查项。
