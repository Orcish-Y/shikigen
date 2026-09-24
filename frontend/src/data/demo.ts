export interface Message {
  id: string;
  role: "user" | "assistant";
  text: string;
  code?: { language: string; filename: string; content: string };
  tool?: { name: string; command: string; output: string };
}

export interface Session {
  id: string;
  title: string;
  group: "今天" | "昨天";
  summary: string;
  messages: Message[];
}

// 仅用于页面框架预览，不代表真实运行结果。
export const demoSessions: Session[] = [
  {
    id: "demo-architecture",
    title: "架构重构与调度器集成",
    group: "今天",
    summary: "会话隔离、流式输出与生命周期",
    messages: [
      {
        id: "m1",
        role: "user",
        text: "我们需要优化 shikigen 的流式响应管道，请帮我梳理前端、Tauri 桌面壳和 Agent 后端之间的职责，以及切换会话时的生命周期。",
      },
      {
        id: "m2",
        role: "assistant",
        text: "可以把工作台拆成三个边界清晰的层次：前端负责交互和运行状态展示，Tauri 提供桌面窗口，Agent 后端负责执行任务。\n\n前端通过 HTTP 发起请求，通过 SSE 观察运行事件。会话切换时释放旧的观察连接，并按会话保存消息与草稿。",
        code: {
          language: "TypeScript",
          filename: "运行状态 · 类型示例",
          content:
            "type RunStatus =\n  | 'running'\n  | 'interrupted'\n  | 'completed'\n  | 'cancelled'\n  | 'error';\n\ninterface RunSnapshot {\n  threadId: string;\n  runId: string;\n  status: RunStatus;\n}",
        },
        tool: {
          name: "read_file",
          command: "docs/frontend-prd.md",
          output: "前端只消费 HTTP 和 SSE 契约，将持久事实投影为界面。",
        },
      },
      {
        id: "m3",
        role: "user",
        text: "如果用户在侧边栏切换了会话，旧会话的任务也要一起取消吗？",
      },
      {
        id: "m4",
        role: "assistant",
        text: "会话切换只关闭当前观察连接，后台任务可以继续执行。取消运行应由用户主动触发独立的取消操作。\n\n重新进入会话后，通过已知的 Run ID 恢复观察；前端按会话隔离事件，避免旧连接的输出进入新会话。",
      },
    ],
  },
  {
    id: "demo-tools",
    title: "工具与 Middleware 设计",
    group: "今天",
    summary: "梳理工具注册与中间件边界",
    messages: [
      {
        id: "t1",
        role: "user",
        text: "工具注册和 Middleware 链应该分别承担什么职责？",
      },
      {
        id: "t2",
        role: "assistant",
        text: "工具注册表负责描述和查找工具；Middleware 链负责围绕调用执行统一的策略，例如日志、审批和异常处理。这样新增工具时，可以复用已有的执行规则。",
      },
    ],
  },
  {
    id: "demo-checkpoint",
    title: "Checkpoint 恢复机制",
    group: "昨天",
    summary: "持久状态与运行恢复",
    messages: [
      { id: "c1", role: "user", text: "Checkpoint 需要保存哪些状态？" },
      {
        id: "c2",
        role: "assistant",
        text: "先明确恢复边界，再保存恢复所需的消息、运行状态和待处理动作。连接、定时器等进程内资源应在恢复时重新建立。",
      },
    ],
  },
];
