# LangGraph 的标识机制：名称、标签、元数据、命名空间与 Run ID

LangGraph/LangChain 中有不少看起来都能“标识一次调用”的字段：`run_name`、`tags`、`metadata`、`langgraph_node`、stream namespace、`checkpoint_ns`、`run_id`。它们并不是同一种标识的不同写法，而是服务于不同层次：

- **调用与追踪层**：`run_name`、`tags`、`metadata`、`run_id`、`parent_run_id`
- **Graph 执行层**：框架元数据，如 `langgraph_node`
- **Graph/子图作用域层**：stream namespace（v2 的 `ns`、v3 的 `namespace`）
- **持久化层**：`checkpoint_ns`
- **流与可见性控制**：`TAG_NOSTREAM`、`TAG_HIDDEN`（本质上仍是特殊 tag）

理解这些层次后，“怎样区分主 Agent 与内部 GoalEvaluator”就会变得清楚：应使用调用级 `tags`/`metadata` 表达语义，用 `run_name` 改善追踪可读性，用 `TAG_NOSTREAM` 控制消息流；不应为了区分一次普通 LLM 子调用而人为创建 subgraph namespace。

> 本文按本仓库当前环境说明：`langgraph==1.2.9`、`langchain-core==1.5.1`、`langchain==1.3.14`。流式 API 同时涉及 v2 和较新的 v3，因此示例会注明版本。

## 一张表看懂它们

| 机制 | 标识对象 | 典型值 | 谁产生 | 是否向子调用传播 | 主要可见位置 | 适合做什么 |
|---|---|---|---|---|---|---|
| `run_name` | 当前 Runnable run/span | `goal_evaluator` | 应用配置 | **不用于给所有子 run 重命名** | LangSmith trace/UI | 让当前调用易读、可分组 |
| `tags` | run/span 的类别集合 | `goal_evaluator` | 应用配置 | 是 | tracing、callbacks、message metadata | 分类、过滤、控制行为 |
| `metadata` | run/span 的结构化属性 | `{"component": "goal_evaluator"}` | 应用配置 | 是 | tracing、callbacks、message metadata | 携带可查询的键值上下文 |
| `run_id` | 一个具体 run/span | UUID | 自动生成或顶层显式指定 | 否；子 run 有自己的 ID | callbacks、LangSmith | 精确定位一次执行 |
| `parent_run_id` | run tree 中的父子关系 | 父 UUID | callback/tracing 系统 | 自动建立关系 | callbacks、LangSmith | 重建调用树、查直接子调用 |
| `langgraph_node` | 当前 Graph 节点位置 | `model`、`tools` | LangGraph 自动注入 | 嵌套调用通常可在 metadata 中看到 | `messages` stream metadata、debug/task metadata | 按 Graph 节点过滤流 |
| stream `ns` / `namespace` | 事件来自哪个 graph/subgraph scope | `("node:task-id",)` | LangGraph 自动生成 | 随子图嵌套形成路径 | stream event envelope | 区分根图与各级子图事件 |
| `checkpoint_ns` | checkpoint 属于哪条 graph/subgraph 持久化支线 | `""`、`"node:uuid|child:uuid"` | LangGraph 自动维护 | 随子图层级派生 | checkpoint config、runtime execution info | 隔离和寻址持久化状态 |
| `TAG_NOSTREAM` | chat model run 的消息流策略 | `nostream` | 应用配置（公共常量） | 作为 tag 传播 | `messages` stream handler | 执行并追踪模型，但不把 token 发到消息流 |
| `TAG_HIDDEN` | 某些 tracing/streaming 环境中的隐藏策略 | `langsmith:hidden` | 框架或应用配置（公共常量） | 作为 tag 传播 | LangGraph debug/task/message 处理 | 隐藏框架内部节点/边；不是安全边界 |

共同点是：它们都能帮助回答“这条数据来自哪里”。不同点在于“哪里”的含义不同——可能是语义组件、一次 span、Graph 节点、子图路径，或 checkpoint 存储分区。选择字段前，应先确定要回答的是哪一种问题。

## 1. `run_name`：给当前 run 一个可读名称

`run_name` 是 `RunnableConfig` 的字段，用来设置**当前调用对应的 tracer run 名称**；未设置时通常使用 Runnable 的类名。LangSmith 会将它用于展示、过滤和分组。[官方 tracing 文档](https://docs.langchain.com/langsmith/trace-with-langchain#customize-run-name)特别强调：给外层 chain 设置 `run_name` 只会改外层 run 的名字，不会自动重命名其中的 LLM 子 run。

```python
response = await model.ainvoke(
  prompt,
  config={"run_name": "goal_evaluator"},
)
```

这里直接调用模型，因此名字对应这次 evaluator 模型 run。它适合人类阅读和按名称聚合，不适合作为唯一身份：同名 run 可以出现任意多次。

## 2. `tags`：扁平、可组合的分类标签

`tags` 是字符串列表，适合回答“这个 run 属于哪些类别”。官方文档确认，经 `RunnableConfig` 附加的 tags 会被子 Runnable 继承，并可用于追踪查询；在 `stream_mode="messages"` 中，也可以从消息 metadata 的 tags 过滤某次 LLM 调用。[LangSmith tags/metadata 文档](https://docs.langchain.com/langsmith/trace-with-langchain#add-metadata-and-tags-to-traces)；[LangGraph 按 tag 过滤消息流](https://docs.langchain.com/oss/python/langgraph/streaming#filter-by-llm-invocation)。

```python
config={"tags": ["goal_evaluator", "internal"]}
```

Tags 的特点是：

- 一个 run 可以有多个 tag，适合多维分类；
- 父级 tags 会进入子调用，因此过滤时要区分“本调用自己设置”与“从祖先继承”；
- tag 只是字符串，普通 tag 默认不会改变执行行为；
- 少数框架保留 tag（如 `nostream`）会触发控制语义。

若要表达 `component=goal_evaluator` 这样的键值关系，metadata 通常比 tag 更准确。

## 3. `metadata`：结构化、可查询的上下文

`metadata` 是 JSON 可序列化的键值字典，同样会被子 Runnable 继承，适合环境、租户、组件、实验版本、关联 ID 等结构化属性。[官方文档](https://docs.langchain.com/langsmith/add-metadata-tags)将 tags 定义为分类字符串，将 metadata 定义为附加信息的键值对。

```python
config={
  "metadata": {
    "component": "goal_evaluator",
    "visible_to_user": False,
  }
}
```

当前 `langchain-core` 的 config 合并实现对普通 metadata key 使用后写覆盖语义，而 tags 会合并并去重；`lc_versions` 是 metadata 合并的特殊例外。对应实现见 `.venv/lib/python3.12/site-packages/langchain_core/runnables/config.py` 的 `_merge_metadata_dicts()` 与 `merge_configs()`。

不要把秘密写入 metadata。它面向 callbacks 和追踪系统，并非机密存储；继承还会扩大其可见范围。另一个陷阱是使用 `langgraph_*` 名称存业务字段：这些通常是框架保留语义，业务 metadata 应使用自己的命名，如 `component` 或带项目名前缀的 key。

## 4. 框架 metadata：`langgraph_node` 表示执行位置

LangGraph 为每个 task 自动组装 metadata，包括 `langgraph_step`、`langgraph_node`、`langgraph_triggers`、`langgraph_path` 和 `langgraph_checkpoint_ns`。本地实现位于 `.venv/lib/python3.12/site-packages/langgraph/pregel/_algo.py`。`stream_mode="messages"` 会把 `(message, metadata)` 一起发出，因此官方推荐按 `metadata["langgraph_node"]` 过滤指定节点的模型 token。[官方示例](https://docs.langchain.com/oss/python/langgraph/streaming#filter-by-node)。

```python
for chunk in graph.stream(inputs, stream_mode="messages", version="v2"):
  if chunk["type"] != "messages":
    continue
  message, metadata = chunk["data"]
  if metadata["langgraph_node"] == "model":
    render(message)
```

`langgraph_node` 与 `tags` 的差别是：

- 节点名来自 Graph 拓扑，通常由框架自动注入；tag 表达应用语义，由应用选择；
- 同一节点内可以发起多个 LLM 调用，它们可能具有相同 `langgraph_node`，却可拥有不同 tag；
- Graph 重构或节点改名会改变 `langgraph_node`，因此它适合 UI 路由和执行调试，不宜充当长期业务标识。

对 middleware 内部的 GoalEvaluator 而言，`langgraph_node` 只能说明它运行在哪个 Graph 节点上下文中，`goal_evaluator` tag 才能精确说明这次 LLM 调用的业务角色。

## 5. Stream namespace：事件来自哪一级子图

开启子图流后，namespace 是从根图到事件发出 scope 的路径。v2 `StreamPart` 使用 `ns: tuple[str, ...]`；根图为 `()`，子图可能为 `("node_name:<task_id>",)`。官方文档说明，设置 `subgraphs=True` 后，根图和子图的事件都会出现，`ns` 用于识别来源。[LangGraph subgraph streaming](https://docs.langchain.com/oss/python/langgraph/streaming#subgraph-outputs)。

v3 event protocol 使用 `params.namespace: list[str]`，根图为 `[]`；每一段是 `"name:runtime_id"`，名称部分较稳定，后缀是每次执行的 runtime ID。[v3 event streaming](https://docs.langchain.com/oss/python/langgraph/event-streaming#event-protocol)。

```text
[]                                      # 根图
["researcher:6f4d"]                    # 一层子图
["researcher:6f4d", "tools:91ac"]     # 更深的执行 scope
```

因此不要比较完整 namespace 字符串来获得跨运行稳定性；runtime/task ID 每次都可能变化。若要长期识别组件，应使用稳定名称部分，或另外附加 tag/metadata。

Namespace 的价值在于结构：它表达嵌套作用域，而 tags 只表达集合成员关系。一次 middleware 内直接执行的 `model.ainvoke()` 是一个子 run，但不是一个 subgraph；为了获得 namespace 而把它包装成 subgraph，通常属于不必要的结构复杂化。

## 6. `checkpoint_ns`：持久化地址，不是展示标签

`checkpoint_ns` 位于 checkpoint 的 configurable 坐标中，用来区分同一 thread 里根图与不同子图的 checkpoint。当前实现以空字符串表示根图；内部 namespace 层级用 `|` 分隔，每层名称和 task ID 用 `:` 分隔。本地常量与注释见 `.venv/lib/python3.12/site-packages/langgraph/_internal/_constants.py`，内存 checkpointer 也以 `(thread_id, checkpoint_ns, checkpoint_id)` 读取和存储，见 `.venv/lib/python3.12/site-packages/langgraph/checkpoint/memory/__init__.py`。

官方 persistence 文档展示的 `StateSnapshot.config` 同时包含 `thread_id`、`checkpoint_ns` 和 `checkpoint_id`，说明它是 checkpoint 寻址的一部分，而非 tracing 名称。[LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence#get-state)。

它与 stream namespace 相关但不等价：

- 二者都反映 graph/subgraph 层级；
- stream namespace 属于事件来源 envelope，面向实时消费；
- `checkpoint_ns` 属于持久化坐标，面向恢复、状态读取和子图隔离；
- 它们的表示形式和稳定性都不是公共业务 ID 契约，不应自行解析后写业务逻辑，除非使用文档明确提供的接口。

## 7. `run_id` 与 `parent_run_id`：一次执行及其调用树

每个 traced run/span 都有唯一 `run_id`。`RunnableConfig.run_id` 可以为当前调用显式提供 UUID，否则框架生成；顶层 run 的 ID 也会成为 trace ID。[官方文档](https://docs.langchain.com/langsmith/trace-with-langchain#customize-run-id)同时指出，直接为 LLM 对象定制 run ID 并非所有场景都支持，因此通常只在顶层设置。

子调用拥有自己的 `run_id`，并通过 `parent_run_id` 指向父 run。它们形成的是**调用树**，不是 Graph 拓扑，也不是 checkpoint 历史。LangSmith 的 run 数据格式展示了 parent、child、grandchild 各自唯一的 ID，以及 `parent_run_id` 如何连接相邻层级。[Run 数据格式](https://docs.langchain.com/langsmith/run-data-format#what-is-dotted_order)。

在经典 `astream_events(version="v2")` 事件里，对应的公开字段是 `parent_ids`：它列出从根 run 到直接父 run 的祖先 ID，根事件则是空列表。`parent_run_id` 是 callback/LangSmith run record 中的直接父 ID；二者都由执行与追踪系统建立，并不是要塞进 `RunnableConfig` 的业务字段。[`astream_events` API reference](https://reference.langchain.com/python/langchain-core/runnables/base/Runnable#langchain_core.runnables.base.Runnable.astream_events)。

适用场景：

- `run_id`：精确查询某一次调用、与外部请求 ID 关联；
- `parent_run_id`：查直接子调用、重建 trace 层级；
- `run_name`：看懂这次调用“是什么”；
- tags/metadata：按属性查找“一类调用”。

不要用 `run_id` 表示 thread。一个 thread 可以包含多个顶层 run；持久化会话应使用 `thread_id`，一次 tracing 执行才使用 `run_id`。

## 8. 两个公共控制 tag

### `TAG_NOSTREAM`

`TAG_NOSTREAM` 的值是 `"nostream"`，用于禁止 chat model 输出进入 `messages` stream。调用仍会执行并返回结果；官方文档明确说明，只是不发出其 token，因此很适合结构化输出、内部评估器和避免重复 UI 输出。[官方 `nostream` 文档](https://docs.langchain.com/oss/python/langgraph/streaming#omit-messages-from-the-stream)。

当前消息流实现会在 `on_chat_model_start` 检查 tag，存在 `TAG_NOSTREAM` 时不登记该模型 run，后续 token 就不会被 message streamer 发出；见 `.venv/lib/python3.12/site-packages/langgraph/pregel/_messages.py`。这意味着它比 `callbacks=[]` 更精确：它控制消息流，却不会为了隐藏 token 而一并关掉 token usage callback 或 tracing。

### `TAG_HIDDEN`

`TAG_HIDDEN` 的值是 `"langsmith:hidden"`，公共常量的说明是“在某些 tracing/streaming 环境中隐藏 node/edge”，见 `.venv/lib/python3.12/site-packages/langgraph/constants.py`。当前 LangGraph 还用它跳过 debug task、task result、node-finished 回调和部分 message/node 输出；相关实现分布在 `pregel/debug.py`、`pregel/_loop.py`、`pregel/_runner.py` 和 `pregel/_messages.py`。

它的作用比 `TAG_NOSTREAM` 更广，也更依赖具体消费者。不要把 `TAG_HIDDEN` 当作权限控制或数据脱敏：常量文档刻意说的是“certain tracing/streaming environments”，不能保证所有 callback、自定义日志或外部 provider 都忽略它。若只想隐藏内部 LLM token，应优先选择语义精确的 `TAG_NOSTREAM`。

## 9. 传播与可见性：最容易踩坑的地方

LangChain 使用调用上下文和 callback manager 将配置传播到嵌套 Runnable。`RunnableConfig` 的本地源码注释明确说明，`var_child_runnable_config` 会把父 config 自动传入调用栈中的子 Runnable；官方 tracing 文档也确认 tags 和 metadata 会被子调用继承。Python 3.11 之前的异步任务对 context variables 传播有限，需要显式传 config；官方 streaming 文档仍保留了这个兼容性提示。[异步传播说明](https://docs.langchain.com/oss/python/langgraph/streaming#filter-by-llm-invocation)。

传播不等于所有字段行为相同：

- tags/metadata 是设计为可继承的属性；
- `run_name` 命名当前 invoked Runnable，不会替所有后代统一改名；
- `run_id` 标识当前 run，子 run 必须拥有不同 ID；
- `parent_run_id` 由 callback/tracer 建立，不是应用随意复用的标签；
- `langgraph_node`、namespace、`checkpoint_ns` 由 Graph 执行框架派生。

另一个坑是把“能在 tracing 中看到”误认为“会出现在消息流”。例如 `run_name` 很适合 LangSmith，但 UI 的 `messages` 消费器通常拿到的是 message、node、tags 和 metadata；若要路由 token，优先按 `langgraph_node`、tags 或 metadata，而不是依赖 trace 展示名称。

## 10. 本仓库 GoalEvaluator 的推荐组合

GoalEvaluator 是 middleware 内部的一次无工具 LLM 调用。它是 Agent run 的子 run，但不是独立 subgraph。下面的配置分别承担三个明确职责：

```python
from langgraph.constants import TAG_NOSTREAM

response = await self.model.ainvoke(
  prompt,
  config={
    "run_name": "goal_evaluator",
    "tags": [TAG_NOSTREAM, "goal_evaluator"],
    "metadata": {"component": "goal_evaluator"},
  },
)
```

- `run_name="goal_evaluator"`：让 trace 中这次模型调用可读；
- `"goal_evaluator"` tag：提供轻量分类，适合 callbacks 和筛选；
- `metadata.component`：提供结构化、可扩展的组件身份；
- `TAG_NOSTREAM`：不让 evaluator 的 `YES/NO + reason` 混入面向用户的 Agent token 流；
- 保留 callbacks：usage 统计和 tracing 仍可观察 evaluator。

这里没有使用 namespace，因为 evaluator 没有独立 Graph scope；也没有手工使用 `checkpoint_ns`，因为 evaluator 不拥有独立 checkpoint；没有固定 `run_id`，因为每次评估都应是一次新的 run。

如果将来要在 UI 里同时展示多个内部模型通道，可以不加 `TAG_NOSTREAM`，转而消费 `(message, metadata)` 并按 `goal_evaluator` tag 或 `metadata["component"]` 路由。但当前需求只是避免内部判断文本出现在用户终端，`TAG_NOSTREAM` 是最小且语义最准确的选择。

## 选择口诀

- 想让 trace **好读**：`run_name`
- 想给调用做**多选分类**：`tags`
- 想携带**结构化属性**：`metadata`
- 想找**唯一一次执行**：`run_id`，沿调用树查找用 `parent_run_id`
- 想知道 token 来自**哪个 Graph 节点**：`langgraph_node`
- 想知道事件来自**哪一级子图**：stream namespace
- 想寻址**哪一份持久化状态**：`thread_id + checkpoint_ns + checkpoint_id`
- 想让内部模型运行但**不输出 token**：`TAG_NOSTREAM`
- 想隐藏框架内部节点/边的部分观测噪音：`TAG_HIDDEN`，但不要把它当安全边界

最重要的原则是：**用结构标识结构，用语义标识语义，用唯一 ID 标识一次实例。** 不要让某个字段同时承担这三种职责。

## 主要来源

- [LangGraph Streaming](https://docs.langchain.com/oss/python/langgraph/streaming)
- [LangGraph Event streaming](https://docs.langchain.com/oss/python/langgraph/event-streaming)
- [LangGraph Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
- [LangGraph Subgraphs](https://docs.langchain.com/oss/python/langgraph/use-subgraphs)
- [LangSmith：Trace LangChain applications](https://docs.langchain.com/langsmith/trace-with-langchain)
- [LangSmith：Add metadata and tags](https://docs.langchain.com/langsmith/add-metadata-tags)
- [LangSmith Run data format](https://docs.langchain.com/langsmith/run-data-format)
