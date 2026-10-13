# 工具执行隔离与沙箱架构调查

基线日期：2026-10-10。本文件根据主流 Agent 系统（OpenClaw、DeepSeek Harness、NousResearch Hermes）的沙箱与安全隔离机制进行横向对比与技术复盘，为自建 Agent Harness 的工具执行隔离设计提供架构参考。

---

## 1. 核心结论与横向对比

| 框架 / 系统 | 是否具备沙箱 | 隔离层级与实现技术 | 典型模式 / 范围控制 | 核心定位与已知安全边界 |
| --- | --- | --- | --- | --- |
| **OpenClaw** | **是**（成熟子系统） | Docker / Podman 容器、SSH 远程机、OpenShell、Crabbox（云微虚机） | `off` / `non-main`（仅子Agent）/ `all` | 控制面与执行面分离；属于纵深防御（Defense-in-Depth），非绝对多租户硬边界；企业版（OCE）提供更高规格隔离 |
| **DeepSeek Harness** (`dsh`) | **是**（可插拔组件） | OS 原生沙箱：Linux `bubblewrap`、macOS `Seatbelt`、本地进程隔离插件 | 插件配置（`sandbox-local` 等） | 开发者预览版（Developer Preview）；曾曝出 CVE-2026-82533（未鉴权 API 导致沙箱绕过）；偏重文件系统限制 |
| **Hermes Agent** (`NousResearch`) | **是**（多后端沙箱） | Docker（支持状态持久化容器）、Local UDS、SSH、Singularity、云端（Modal, Vercel Sandbox） | 配置文件绑定（`cli-config.yaml`） | 支持跨轮次保持依赖与环境（如持久 pip 安装）；需要注意宿主敏感目录挂载与环境变量泄露边界 |

---

## 2. OpenClaw 沙箱机制深度拆解

### 2.1 架构设计：控制面与执行面解耦
OpenClaw 采用 **Hub-and-Spoke / Gateway** 架构：
- **Gateway（宿主控制面）**：驻留在宿主机上，负责 Agent Loop 驱动、会话状态持久化（Transcript / Session Store）、消息路由及策略检查。
- **Sandbox Runner（隔离执行面）**：当 Agent 触发高风险工具（如执行 Shell 命令、文件系统任意修改、执行动态代码）时，Gateway **不直接在本地宿主运行**，而是将工具调用委托给配置的沙箱后端执行。

### 2.2 支持的沙箱后端（Backends）
1. **Docker / Podman**：最常见的本地隔离方案，启动轻量容器代理运行命令与文件变更。
2. **SSH / 远程主机**：将工具执行卸载（Offload）到专门的远程测试机或独立运行节点。
3. **OpenShell**：在受限的远程终端环境中执行命令。
4. **Crabbox**：租用云端基础设施或轻量微虚机（MicroVM）执行一次性或短期任务。

### 2.3 隔离模式与作用域（Modes & Scopes）
- `off`：沙箱关闭，工具在宿主机当前工作目录（CWD）直接运行（依靠基础白名单策略约束）。
- `non-main`：仅针对非主会话/派生会话（如子 Agent、后台 Task）启用沙箱，主会话保持在宿主以便高效交互。
- `all`：全局所有会话与工具执行一律强制进入沙箱隔离。

### 2.4 CLI 运维与审计命令
- `openclaw sandbox list`：查看当前正在运行的沙箱容器/执行实例。
- `openclaw sandbox explain`：审计特定工具调用为何被允许或拦截，检查生效的作用域与权限策略。
- `openclaw sandbox recreate`：当容器内环境被 Agent 污染或损坏时，强制销毁并重建初始沙箱环境。

### 2.5 安全定位与局限
- **纵深防御而非绝对安全壁垒**：官方文档明确强调，基于容器的沙箱旨在限制 Agent 操作的“爆炸半径（blast radius）”，防范意外破坏或常规脚本注入，但无法彻底杜绝高级容器逃逸或无限制网络外发（需配合严苛的网络隔离策略）。
- **企业版诉求**：多租户场景下需使用 OpenClaw Enterprise（OCE）结合 Hypervisor 级别（如 Firecracker/微虚机）隔离。

---

## 3. DeepSeek Harness 与 Hermes 对照

### 3.1 DeepSeek Harness (`deepseek-ai/deepseek-harness`)
- **设计思想**："Everything is a plugin"，Sandbox 是 Harness 六大可插拔子系统之一（Model Adapter、Tool Registry、Session Store、Agent Loop、Sandbox 等）。
- **技术路线**：重度依赖宿主 OS 级别的轻量隔离工具（Linux `bubblewrap` / macOS `Seatbelt`）。
- **安全性警戒**：目前处于 Developer Preview 阶段，官方未完成正式安全审计。2026年9月曾暴露出 CVE-2026-82533 漏洞（Agent 可调用本地 Harness 暴露的未认证 API 自行解除限制）。因此官方建议如果用于高危测试，外部仍需套上一层虚拟机或 Docker。

### 3.2 Hermes Agent (`NousResearch/hermes-agent`)
- **设计思想**：面向长时运行与“自我进化（Self-improving）”的 Agent，工具调用支持跨轮次累积状态。
- **技术路线**：支持多种后端（Docker、SSH、Modal 等）。其 Docker 后端的一大特色是**持久化容器（Persistent Sandbox Environment）**，允许 Agent 在沙箱内执行 `pip install`、拉取依赖后，在后续会话中继续复用，而不是每次调用都销毁重来。
- **隔离考量**：需要防止将宿主敏感文件（如根目录、密钥、配置文件）通过挂载（Volume Mount）或 `PYTHONPATH` 暴露进沙箱。

---

## 4. 对自研 Agent Harness 的设计启示

在构建自主可控的 Agent Harness 时，沙箱设计应遵循以下分层契约：

1. **控制层（Harness / Graph）与执行层（Tool Runner）分离**：
   - Agent Loop、State、Checkpoint、Memory 保持在宿主服务进程中。
   - 工具系统通过接口抽象（如 `ExecutionRunner` 协议）驱动具体执行。
2. **分级安全策略（Execution Strategy）**：
   - **只读 / 安全工具**（如内置计算、预定义查表）：在宿主进程内直接运行。
   - **高危 / 任意代码工具**（如 Bash、Python REPL、网络爬取）：
     - 开发阶段：本地受限子进程（CWD 白名单 + 路径遍历检查）。
     - 进阶阶段：Docker 容器执行器（可配置挂载点与网络策略）。
3. **环境生命周期管理**：
   - 区分**临时性（Ephemeral）沙箱**（单次执行即销毁，防状态污染）与**状态化（Persistent）沙箱**（保留开发环境依赖，适合多步骤编码 Agent）。

---

## 5. 参考来源

- [OpenClaw Architecture & Sandboxing Documentation](https://docs.openclaw.ai/concepts/sandboxing)
- [OpenClaw Sandboxing Configuration & Backends](https://github.com/openclaw/openclaw/blob/main/docs/cli/sandboxing.md)
- [DeepSeek Harness Repository & Security Disclosures](https://github.com/deepseek-ai/deepseek-harness)
- [NousResearch Hermes Agent Documentation](https://nousresearch.com/hermes-agent/)
