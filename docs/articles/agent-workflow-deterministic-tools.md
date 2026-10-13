# 深度拆解 Agent 工作流：大模型究竟是如何精准调用固定代码节点的？

> **导语**：在搭建 AI Agent 工作流（Workflow/DAG）时，很多初学者常常有一个直觉误区：“大模型是否像人类一样拥有上帝视角，看着画布上的节点连线，知道下一步该去调用哪个人写的 Python 函数？”  
> 答案是否定的。大模型对你的流程图、画布、节点一无所知。  
> 那么，工作流引擎究竟是如何让一个“只会概率生成文本”的模型，严丝合缝地触发人写的固定代码，并准确填入参数的？本文将为你揭开这层工程面纱。

---

## 一、打破直觉误区：大模型其实“戴着眼罩”

在许多低代码 Agent 平台（如 Dify、Coze）或代码级图引擎（如 LangGraph）中，我们常常设计类似这样的链路：

```
[用户输入] ──> [LLM 意图识别] ──> [固定代码节点 node_A] ──> [下游处理]
```

很多人的第一反应是：*模型在推理时知道后面连着 node_A。*

**工程真相是：**
1. **大模型没有任何全局图感知能力**。它不知道画布、不知道 DAG、更不知道写代码的是张三还是李四。
2. 模型的所有“精准调用”，全靠**工作流引擎（Python 运行时）在发起单次 API 请求的那一瞬间，通过协议“硬塞”给它的上下文和约束**。
3. **大模型从不直接运行代码**。它只是一个“填表工具”——根据上下文提取参数，真正的代码永远是由背后的工作流引擎在本地沙箱或子进程中执行的。

---

## 二、桥梁的建立：人写的 Python 代码如何变成 LLM 能懂的“说明书”？

假设开发者在工作流中手写了一个执行节点 `node_A`：

```python
def calculate_mortgage(loan_amount: float, years: int, rate: float = 0.035) -> dict:
    """计算房贷月供及总利息。
    
    Args:
        loan_amount: 贷款总金额（万元）
        years: 贷款年限
        rate: 年利率，默认 0.035
    """
    ...
```

大模型是不能直接读 Python 函数体代码的，工作流引擎在**初始化/编译阶段**做了两件事：

### 1. 签名反射（Reflection）
引擎利用 Python 的 `inspect` 和 `pydantic`，读取函数的类型注解与 Docstring。

### 2. 编译为标准化 JSON Schema
引擎将这段函数提取为一段标准的 JSON Schema（OpenAPI 规范）：

```json
{
  "name": "calculate_mortgage",
  "description": "计算房贷月供及总利息",
  "parameters": {
    "type": "object",
    "properties": {
      "loan_amount": { "type": "number", "description": "贷款总金额（万元）" },
      "years": { "type": "integer", "description": "贷款年限" },
      "rate": { "type": "number", "description": "年利率，默认 0.035" }
    },
    "required": ["loan_amount", "years"]
  }
}
```
**这一步完成了“人写代码契约”向“LLM 交互契约”的转换。**

---

## 三、两种实现范式：模型如何触发固定节点？

当工作流走到模型节点，且下一步**必须**调用这个固定代码节点时，业界有两种主流实现路径：

### 范式 1：强制工具调用（Forced Tool Calling）——最标准的做法

在 OpenAI、Claude、DeepSeek 等现代大模型 API 中，都支持 `tools` 和 `tool_choice` 参数。

```
                    ┌──────────────────────────────────────────────┐
                    │            工作流引擎 (Python 运行时)         │
                    └───────┬──────────────────────────────▲───────┘
  1. 剥夺废话权利           │                              │ 3. 拦截 ToolCall
     tool_choice: "node_A"  │                              │    执行 Python 代码
                            ▼                              │
                    ┌──────────────────────────────┐       │
                    │          大语言模型          │───────┘
                    │                              │
                    │ 物理上只能生成固定 JSON 参数  │
                    └──────────────────────────────┘
```

1. **引擎发起请求**：将 `calculate_mortgage` 的 Schema 放入 `tools` 列表。
2. **强制指定调用（关键秘诀）**：
   在请求参数中加入：
   ```json
   "tool_choice": {
     "type": "function", 
     "function": {"name": "calculate_mortgage"}
   }
   ```
   **这一行的威力在于：剥夺了模型回答自然语言闲聊的权利。** 模型在概率解码时被强行锁定，必须且只能输出调用该函数所需要的 JSON 参数。
3. **模型吐出意图**：模型返回一个 `AIMessage`，其 `content` 为空，而 `tool_calls` 包含提取好的实参：
   ```json
   {"loan_amount": 120.0, "years": 30}
   ```
4. **引擎本地拦截并执行**：引擎解析出字典，在本地执行 `calculate_mortgage(loan_amount=120.0, years=30)`。

---

### 范式 2：结构化输出管道（Structured Outputs）——轻量数据流做法

如果 `node_A` 只是一个普通的业务逻辑节点（开发者不想走复杂的 ToolCall / 消息协议），现代工程框架倾向于使用 **Structured Outputs（结构化输出）**。

* **做法**：直接把 `node_A` 的入参定义为一个 Pydantic 模型。
* **效果**：引擎通过底层语法约束（Constrained Decoding），迫使 LLM 的响应直接就是一个合法的 JSON 字符串。
* **流程**：
  ```
  自然语言输入 ──> [LLM Structured Output] ──> 解析为 Python Dict ──> 直接传参 node_A(**args)
  ```
  在这种模式下，模型扮演的角色非常纯粹——**非结构化自然语言到强类型参数字典的翻译器**。

---

## 四、链路闭环：输出结果如何流转给后续节点？

执行完 `node_A` 后，我们得到了一个返回值字典：
`{"monthly_payment": 5389.2, "total_interest": 74.0}`。

后续节点该如何消费它？这取决于下游是**模型节点**还是**另一个代码节点**：

### 场景 A：下游是模型节点（如何让模型读懂结果？）

业界标准方案是 **`ToolMessage` 回传法**（OpenAI / LangChain 规范）：

引擎把代码的输出包装成一条角色为 `tool` 的历史消息，追加到对话序列中：

```json
[
  {"role": "user", "content": "我想贷 120 万，分 30 年，帮我算算月供。"},
  {"role": "assistant", "tool_calls": [{"id": "call_01", "name": "calculate_mortgage", ...}]},
  {
    "role": "tool",
    "tool_call_id": "call_01",
    "content": "{\"monthly_payment\": 5389.2, \"total_interest\": 74.0}"
  }
]
```

当把这个完整的列表发给下游模型时，下游模型就像人类翻阅上下文笔记一样，立刻理解了工具执行的数据结果，从而生成通俗易懂的回答：
> *“为您计算完毕，您每月需还款约 5389 元，总利息约为 74 万元。”*

---

### 场景 B：下游是代码节点 `node_B`，但入参 Key 不匹配怎么办？

这是工程上最常见的尴尬情况：
* `node_A` 输出：`{"monthly_payment": 5389.2, "total_interest": 74.0}`
* `node_B` 入参期望：`{"amount": float, "currency": str}`
（语义吻合，但字典键名完全不同）

业界有三种经典解决模式：

```
模式 1: 字段映射表 (Field Mapping)
       node_B.amount   <── A.monthly_payment
       node_B.currency <── "CNY" (固定值)

模式 2: 共享黑板状态 (Shared State - LangGraph 方案)
       全局 State 字典作为中间媒介，各节点从 State 取所需字段。

模式 3: 适配器节点 (Adapter / Transform Lambda)
       在 A 与 B 之间挂载一个轻量转换函数，清洗并重塑字典结构。
```

其中，**共享黑板状态（Shared State）**是 LangGraph 和现代 Agent Harness 最推崇的做法——节点之间不产生直接的强耦合调用，而是共同读写一个全局状态切片。

---

## 五、实战落地：用户编写的代码工具如何接入 LangGraph？

当我们把上述原理落实到目前最主流的图编排框架 **LangGraph** 时，用户编写的 Python 代码工具有三种不同的工程接入形态，取决于具体的业务定位：

### 1. 形态一：直接作为普通图节点（Node 模式，最推荐）
如果该代码是工作流中**步骤确定的环节**（例如：第 2 步必然执行数据清洗或特定算法计算），**它完全不需要被封装为 Tool，直接作为图的一个 Node 是最轻量高效的**。

* **核心契约**：入参为图的全局状态 `State`，返回值是对 `State` 的增量更新字典。
```python
from typing import TypedDict
from langgraph.graph import StateGraph, START, END

class WorkflowState(TypedDict):
    raw_query: str
    cleaned_data: dict
    final_report: str

# 用户编写的执行代码函数
def user_clean_node(state: WorkflowState) -> dict:
    raw = state["raw_query"]
    # 纯 Python 业务逻辑...
    return {"cleaned_data": {"normalized": raw.strip().upper(), "length": len(raw)}}

builder = StateGraph(WorkflowState)
builder.add_node("clean_data", user_clean_node)
builder.add_edge(START, "clean_data")
builder.add_edge("clean_data", END)
graph = builder.compile()
```
* **特点**：零协议开销，无需经过任何 LLM 序列化转换，100% 确定性毫秒级执行。

---

### 2. 形态二：作为模型调用的标准工具（ToolNode 模式）
如果这段代码需要**由大模型动态决定何时调用、或者由模型从对话中提取入参填入调用**，则应接入 LangGraph 的官方 **`ToolNode`**。

* **接入四步曲**：
  1. **封装工具**：使用 `@tool` 装饰器，利用类型提示和 Docstring 自动提取 Schema。
  2. **模型绑定**：`model.bind_tools([user_tool])`（若必须调用则加 `tool_choice`）。
  3. **挂载节点**：实例化 `ToolNode([user_tool])` 并注册为名为 `"tools"` 的节点。
  4. **条件连线**：使用 `tools_condition` 判断模型是生成了普通文本还是 `tool_calls`，以此决定是结束还是跳转到工具节点。

```python
from langchain_core.tools import tool
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.graph import MessagesState, StateGraph, START

@tool
def user_mortgage_tool(loan_amount: float, years: int) -> dict:
    """计算房贷核心指标。"""
    return {"monthly": loan_amount / (years * 12)}

# 实例化工具节点
tool_node = ToolNode([user_mortgage_tool])

builder = StateGraph(MessagesState)
builder.add_node("agent", agent_node)
builder.add_node("tools", tool_node)

builder.add_edge(START, "agent")
builder.add_conditional_edges("agent", tools_condition)  # 有调用走 tools，无调用结束
builder.add_edge("tools", "agent")                       # 工具执行后回传给 agent
graph = builder.compile()
```

---

### 3. 形态三：动态代码接入（低代码平台 / 运行时动态字符串）
如果场景是低代码平台或 Web 界面——用户在浏览器端写了一段 Python 代码（字符串格式），后端需要在运行期动态把它挂载为工具：

可以使用 **`StructuredTool.from_function`** 结合 Pydantic 动态构建：

```python
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

# 假设用户提交的代码在沙箱中动态加载成了 Python 函数 user_fn
def user_fn(x: int, y: int) -> int:
    return x * y + 10

class DynamicInputSchema(BaseModel):
    x: int = Field(description="参数 x")
    y: int = Field(description="参数 y")

# 运行时动态包装为合法 Tool
dynamic_tool = StructuredTool.from_function(
    func=user_fn,
    name="user_custom_calc",
    description="用户动态提交的计算工具",
    args_schema=DynamicInputSchema
)

# 动态传入 ToolNode 挂载使用
tool_node = ToolNode([dynamic_tool])
```

---

## 六、延伸思考：工作流中是否存在跨轮次持久记忆？

很多开发者在搞清工具调用后，会进一步追问：**工作流执行完后，还能记住多轮上下文吗？**

结论是：
* **单次任务管道（Task Workflow）**：**默认没有记忆**。输入数据，顺序走完所有节点，输出结果后整张图的内存完全销毁，每次触发都是一张纯净的白纸。
* **交互式工作流（Conversational Workflow）**：**有记忆，但必须显式挂载 Checkpointer**。
  - 在编译图时指定检查点持久化器：`builder.compile(checkpointer=MemorySaver())`（生产环境使用 `SqliteSaver` 或 `PostgresSaver`）。
  - 在运行时传入会话标识：`config={"configurable": {"thread_id": "session_001"}}`。
  - **工作流的记忆不仅是记聊天文字，而是把整张图的业务状态机（订单号、当前所处节点、中间计算缓存）完整冻结存盘**，下一轮唤醒时可直接从断点继续流转。

---

## 七、工业级全景心智模型（Mental Model）

理解 Agent 工作流调用固定工具，最生动的比喻是**戏剧剧组**：

* **工作流引擎（Harness / Runtime）是“总导演”**：它掌握整本剧本（DAG 拓扑），控制每个阶段谁出场，维护全局状态。
* **固定代码节点（node_A）是“道具与技术组”**：拥有真实的执行能力（计算、写库、发邮件），但不会思考。
* **大模型（LLM）是“蒙着眼睛的演员”**：它不知道整场戏的来龙去脉。导演递给它一张特定的表格（Schema），勒令它必须把表格填满（`tool_choice`）。演员凭借对台词（上下文）的理解填完表格交还给导演，导演再转身交给技术组执行。

---

## 八、结语

Agent 工作流的精髓，从来不是**“期待大模型具备通天彻地的自主意识”**，而是**“用确定性的软件工程契约，去约束并驯服不确定的概率大模型”**。

通过 **反射生成 Schema $\to$ 强制工具约束（`tool_choice`）$\to$ 引擎拦截执行 $\to$ 消息/状态回填**，开发者才能在不确定的自然语言与绝对严谨的代码系统之间，架起一座可靠的高速公路。

