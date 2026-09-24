---
name: langgraph-storage-strategy
description: LangGraph agent 的六种存储位置：State、Runtime Context、Messages、Middleware 字段、Store、外部缓存的作用、区别和选择策略
metadata:
  type: reference
---

# LangGraph Agent 状态存储全景：六种存储位置的选择策略

在 LangGraph agent 里，你的数据可以放在六个位置：**State**、**Runtime Context**、**Messages**、**Middleware 实例字段**、**Store**、**外部内存/缓存**。它们的生命周期、可变性和持久化方式各不相同，选错了会导致数据丢在重启后、共享到不该共享的地方、或者被 checkpoint 序列化拖垮性能。

本文以 `langgraph>=1.2` 的 API 为准，用 `shikigen-agent` 项目中的实际模式做例子。

---

## 速查表

| 位置 | 可变 | 持久化 | 作用域 | 典型用途 |
|---|---|---|---|---|
| **State** | 是，通过 reducer | 是（checkpointer） | 单 thread | 节点间工作状态 |
| **Runtime Context** | 不建议 | 否 | 单次 `invoke` | 配置和注入依赖 |
| **Messages** | 是（本质是 state） | 是（checkpointer） | 单 thread | 对话记录和可从对话推导的数据 |
| **Middleware 实例字段** | 是 | 否 | 所有 run 共享 | 全局配置、共享资源 |
| **Store** | 是 | 是 | 跨 thread | 长期记忆、用户档案 |
| **外部内存/缓存** | 是 | 取决于实现 | 自定义 | 特殊协调场景 |

---

## 1. State —— 节点间的工作状态

### 是什么

State 是 LangGraph 最核心的概念。它是一个 `TypedDict`，graph 的每个节点返回 `dict` 来更新它。更新不是覆盖而是通过 **reducer**（默认合并 dict，`messages` 字段用 `add_messages` 追加）。

```python
# shikigen-agent 中的实际例子
from langchain.agents.middleware import AgentState

class GoalAgentState(AgentState):
    goal_objective: NotRequired[str]
    goal_status: NotRequired[Literal["inactive", "running", "satisfied", "exhausted"]]
    goal_reason: NotRequired[str]
    goal_continuations: NotRequired[int]
    goal_start_index: NotRequired[int]
```

### 特点

- **可变**：节点返回的 dict 通过 reducer 合并进 state，下一跳节点读到的是更新后的值
- **持久化**：有 checkpointer 时会自动序列化到磁盘/数据库，重启恢复
- **作用域**：绑定到 `thread_id`，同一 thread 内的多轮对话共享同一个 state
- **隔离性**：不同 `thread_id` 的 state 互不干扰

### 什么时候用 State

```
✅ 数据需要跨节点传递，且下一跳节点依赖上一跳的输出
✅ 数据需要在多轮 /goal continue 中累积（比如 goal_continuations 计数器）
✅ 数据需要随 checkpoint 持久化，支持中断恢复
```

```
❌ 不要用来存大文件内容或二进制数据（会被序列化到 checkpoint）
❌ 不要用来存全局配置（会冗余存储在每个 thread 的 checkpoint 里）
❌ 不要用来存跨用户的共享数据（store 才是正确位置）
```

### 在 middleware 中读写 State

```python
class GoalMiddleware(AgentMiddleware[GoalAgentState]):
    state_schema = GoalAgentState  # 声明扩展字段

    def before_agent(self, state: GoalAgentState, runtime: Runtime[None]) -> dict:
        """读取 state，返回要合并的更新"""
        if state.get("goal_status") == "satisfied":
            return {}  # 已完成，不再处理
        # ... 返回更新后的字段
        return {"goal_status": "running", "goal_continuations": 1}
```

---

## 2. Runtime Context —— 本次调用的配置和依赖

### 是什么

Runtime Context 在 LangGraph 中有两层含义：

**A. `Runtime` 对象** —— 注入到节点/middleware 的运行环境，包含 `context`、`store`、`stream_writer`、`execution_info` 等字段。它是读为主的对象。

**B. `Runtime.context`** —— 你在创建 graph 时通过 `context_schema` 声明的自定义对象，在调用时通过 `context=...` 传入。

```python
from dataclasses import dataclass
from langgraph.runtime import Runtime

@dataclass
class MyContext:
    user_id: str
    tenant_id: str
    db_connection: Any       # 注意：放资源要慎重，见下文

# 创建时声明
agent = create_agent(
    model=model,
    tools=tools,
    context_schema=MyContext,
)

# 调用时传入
async with await agent.astream_events(
    {"messages": [new_message]},
    config={"configurable": {"thread_id": "thread-1"}},
    context=MyContext(user_id="u1", tenant_id="t1", db_connection=conn),
    version="v3",
) as event_stream:
    ...

# 在 middleware 中读取
def before_agent(self, state, runtime: Runtime[MyContext]):
    user_id = runtime.context.user_id  # "u1"
```

### 特点

- **不建议修改**：官方定义为 "static context for the graph run"，类比 HTTP 请求的 request context
- **不持久化**：不在 checkpoint 中，重启后丢失
- **作用域**：单次 `invoke()` / `astream_events()` 调用。同一 thread 的不同调用可以传不同的 context
- **不适合放可变状态**：如果你在 middleware 里改了 `runtime.context.user_id = "u2"`，这在设计上是不推荐的，且每次调用重新传入 context 本身就意味着它不是"累积"的

### 什么时候用 Runtime Context

```
✅ 配置数据：user_id、tenant_id、语言偏好
✅ 注入依赖：数据库连接池、HTTP client、模型实例
✅ 单次调用上下文：本次请求的 trace_id、请求来源
```

```
❌ 不要用来存在一次调用过程中会变化的数据（用 State）
❌ 不要用来存需要跨调用持久化的数据（用 Store）
❌ 不要把大对象放在 context 里期望它被 checkpoint（它不会被持久化）
```

### `RunnableConfig.configurable` vs `Runtime.context` 的区别

`config["configurable"]` 是一个自由 dict，你可以在里面塞任意键值对（比如 `thread_id`），它会随 checkpoint 传递。而 `Runtime.context` 是类型安全的、结构化的，不随 checkpoint 持久化。简单区分：

- **`configurable`**：给框架/checkpointer 用的配置（`thread_id`、`checkpoint_ns` 等）
- **`context`**：给你的业务逻辑用的依赖注入

---

## 3. Messages —— 对话历史和可从对话推导的数据

### 是什么

Messages 是 `AgentState` 中的一个特殊字段（`messages: Annotated[list[AnyMessage], add_messages]`），它的 reducer `add_messages` 处理追加、合并和替换语义，而不是简单覆盖。

### 特点

- **可变**：每轮对话后 LLM 响应和 tool 调用/结果都追加到 messages
- **持久化**：作为 state 的一部分随 checkpointer 持久化
- **特殊 reducer**：`add_messages` 会按 message ID 去重合并，支持 `ToolMessage` 替换占位符
- **是对话的唯一真相源**：LangGraph agent 的所有节点（model、tools）都从 `state["messages"]` 读写

### 什么时候从 Messages 推导数据，什么时候单开 State 字段

一个常见的纠结：我有一个计数器 `goal_continuations`，是放 state 里还是从 messages 里"数出来"？

```
✅ 单独 State 字段：需要精确控制且值不是 messages 的简单投影
   — goal_continuations: 计数器，中间件每次 +1
   — goal_status: 状态机，有 running/satisfied/exhausted 等
   — 这些值有独立于消息内容的意义，单开字段是正确的

✅ 从 messages 推导：值是 messages 的确定函数
   — "上一轮有几个 tool_call" → 扫 messages 即可
   — "对话是否以 user message 结尾" → 检查 last message 类型
   — 不需要额外维护一致性
```

**原则**：如果信息可以从 messages 唯一确定，就不要在 state 里重复存储。重复存储 = 两个真相源 = 必然不一致。

---

## 4. Middleware 实例字段 —— 全局配置和共享资源

### 是什么

Middleware 是一个类实例，`__init__` 中的字段在 graph 的整个生命周期内存在，所有 thread 共享。

```python
class GoalMiddleware(AgentMiddleware[GoalAgentState]):
    def __init__(self, evaluator: GoalEvaluator, max_continuations: int = 5):
        self.evaluator = evaluator            # 共享的模型实例
        self.max_continuations = max_continuations  # 全局配置
```

### 特点

- **可变**：Python 对象字段，可以随意改
- **不持久化**：进程重启后回到 `__init__` 的初始值
- **作用域**：**跨所有 thread 和 run 共享**，是全局单例
- **线程安全需自行保证**：LangGraph 不会帮你加锁

### 什么时候用 Middleware 实例字段

```
✅ 全局配置常量：max_continuations、超时时间、feature flag
✅ 共享资源：LLM 客户端实例、数据库连接池、HTTP session
✅ 无状态的工具函数引用：evaluator、validator 等
```

```
❌ 不要存放"当前 run"的状态（所有 run 会互相覆盖！）
❌ 不要存放需要持久化的数据（重启丢失）
❌ 不要存放需要在多个 middleware 之间传递的中间结果（用 State）
```

### 一个容易踩的坑

```python
class BadMiddleware(AgentMiddleware):
    def __init__(self):
        self.current_user_id = None  # 🔴 危险！

    def before_agent(self, state, runtime):
        self.current_user_id = runtime.context.user_id
        # 两个并发请求会互相覆盖！
```

**正确做法**：从 `runtime.context` 中读取，不要缓存到实例字段。

---

## 5. Store —— 跨 thread 的长期记忆

### 是什么

LangGraph 的 `BaseStore` 是跨 thread 的持久化键值存储，支持分层命名空间和可选的向量搜索。典型实现有 `InMemoryStore`（开发用）和 `SqliteStore`/`AsyncSqliteStore`（生产用）。

```python
from langgraph.store.memory import InMemoryStore

store = InMemoryStore()

# 存储用户档案
store.put(("users",), "user_123", {"name": "Alice", "preferences": {...}})

# 跨 thread 读取
user_data = store.get(("users",), "user_123")

# 在 graph 中使用
agent = create_agent(model=model, tools=tools, store=store)
```

在 middleware/node 中通过 `Runtime.store` 访问：

```python
def before_agent(self, state, runtime: Runtime[MyContext]):
    if runtime.store:
        profile = runtime.store.get(("users",), runtime.context.user_id)
```

### 特点

- **可变**：put/delete 操作即时生效
- **持久化**：`SqliteStore` 写磁盘，重启保留
- **作用域**：**跨 thread**，是所有对话共享的全局记忆
- **命名空间**：`("users",)` vs `("sessions", "thread_123")`，自然的层级隔离

### 什么时候用 Store

```
✅ 用户档案和偏好：跨会话的个性化信息
✅ 跨 thread 共享的知识：FAQ、学习到的规则
✅ 需要长期保留的记忆：用户反馈、已完成的任务记录
✅ 不适合放 state 的大对象：文档摘要、向量索引
```

```
❌ 不要用来存单次对话的临时状态（State 更合适，有 checkpoint 自动管理生命周期）
❌ 不要用来存高频更新的计数器（Store 没有 State 的 reducer 语义，需要自己处理竞态）
```

### Store vs State 的决策

| 维度 | State | Store |
|---|---|---|
| 粒度 | 每个 thread 独立 | 跨 thread 共享 |
| 生命周期 | 随 thread（可删除 thread 清理） | 显式管理 |
| 更新语义 | Reducer 合并 | 直接覆盖 |
| 典型读写频率 | 每个节点都读写 | 少数节点/中间件按需访问 |

---

## 6. 外部内存/缓存 —— 特殊协调场景

### 是什么

进程内的共享数据结构（如 dict、queue），不走任何 LangGraph 的持久化机制。你的项目中使用这种模式来实现 abort 信号：

```python
# harness/loop.py 中的 abort_event
async def run_agent_loop(agent, new_message, *, record: RunRecord, ...):
    abort_task = asyncio.create_task(record.abort_event.wait())
    # 外部代码 set() 这个 event，loop 立即感知并取消
```

### 特点

- **可变**：完全由你控制
- **不持久化**：进程重启丢失
- **异步安全需要自行处理**：`asyncio.Event` 是安全的；普通 dict 需要锁
- **不被 LangGraph 感知**：checkpoint、中断恢复都对它无感

### 什么时候用外部缓存

```
✅ 进程内信号：abort、pause、drain 等控制信号
✅ 跨并发的临时协调：并发限制信号量、去重集合
✅ 性能敏感的热数据缓存：避免每次从 Store/数据库读取
✅ 与 LangGraph 生命周期无关的外部状态
```

```
❌ 不要用来取代 State/Store（会丢失持久化和 checkpoint 的好处）
❌ 不要在分布式部署中依赖进程内共享（改用 Redis 等外部存储）
```

---

## 决策流程图

```
"这块数据应该放哪里？"
│
├─ 是否与单次对话绑定？
│  │
│  ├─ 是 → 单次对话内是否需要跨节点传递？
│  │  │
│  │  ├─ 是 → 是否需要随 checkpoint 持久化？
│  │  │  ├─ 是 → State（通过 state_schema 扩展)
│  │  │  └─ 否 → Runtime Context
│  │  │
│  │  └─ 否 → 它本来就是对话内容吗？
│  │     ├─ 是 → Messages（不用额外存）
│  │     └─ 否 → 从 Messages 可以推导吗？
│  │        ├─ 是 → 不用存，推导即可
│  │        └─ 否 → 为什么它"不需要跨节点传递"？重新审视设计
│  │
│  └─ 否 → 是否需要跨对话/跨用户共享？
│     │
│     ├─ 是 → Store
│     │
│     └─ 否 → 是配置常量还是共享资源？
│        ├─ 是 → Middleware 实例字段
│        └─ 否 → 需要实时协调或外部队列？
│           ├─ 是 → 外部内存/缓存
│           └─ 否 → 重新审视：也许不需要存
```

---

## shikigen-agent 中的实际模式

回顾本项目的存储分布：

| 数据 | 位置 | 为什么 |
|---|---|---|
| `goal_objective`, `goal_status`, `goal_continuations` | State（GoalAgentState） | 在多轮 /goal continue 中累积，需要 checkpoint |
| `thread_id` | `config["configurable"]` | 框架要求的 checkpointer 配置 |
| `evaluator` (LLM 实例) | Middleware 实例字段 | 全局共享，无需持久化 |
| `max_continuations` | Middleware 实例字段 | 静态配置常量 |
| `abort_event` | 外部 `asyncio.Event` | 进程内实时控制信号，与 LangGraph 生命周期无关 |
| `RunRecord` | 外部对象 | 管理 stream 和元数据，生命周期由 harness 控制 |
| checkpoint 数据 | JsonCheckpointer → 磁盘文件 | 框架自动管理 |

目前项目没有使用 `Runtime.context`（`Runtime[None]`）和 `Store`，这两个是未来的扩展点：

- **加上 `context_schema`**：可以用 `context` 传入 `run_id`、用户身份等，替代目前通过 `config["configurable"]` 传自定义值的做法
- **加上 `Store`**：实现跨 thread 的用户记忆，比如"用户上次偏好什么工具"
