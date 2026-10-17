# Python 工具支持 async main 的后续方案

状态：待实施。记录日期：2026-10-17。

目标是在保留同步 `def main` 的基础上，支持协程入口 `async def main`。本次只记录方案，不修改运行行为。现行行为见 [Python 工具执行说明](python-tool-execution.md)。

## 当前行为与引入原因

当前 Python 工具入口必须是唯一的顶层同步函数。后端静态解析和子进程运行时都拒绝异步入口，前端本地分析也会阻止保存和测试。

工具内部的同步网络请求不会因为等待网络而占住后端事件循环：后端通过 `asyncio.create_subprocess_exec` 启动独立 Python 子进程，再通过 `await process.wait()` 等待。阻塞发生在工具子进程中；依赖该结果的 Agent 流程等待，后端仍可处理其他请求。

支持异步入口的价值是让工具直接使用异步客户端，并在单次工具调用内部并发完成互不依赖的 I/O。例如同时查询两个接口，全部完成后返回合并结果。异步入口不会自动让 Agent 提前调用下一次 LLM，也不会自动让多个工具调用并发；这些仍由调用流程和调度策略决定。

## 目标行为

- 同时支持普通同步函数和协程函数作为 `main`，两者共用参数解析、输入校验和严格 JSON 返回协议。
- Agent 或测试调用方仍等待工具完成后取得结果，入口类型不改变等待语义。
- 同步入口返回协程对象时，继续按非法返回值处理；本次只为声明为协程函数的入口运行事件循环。
- 保留现有参数和类型限制，不扩展容器类型、nullable、装饰器、复杂签名或生成器入口。
- 普通生成器和异步生成器均拒绝；`async def main(): yield 1` 不属于可接受的协程入口。

## 改动位置

| 位置 | 后续改动 |
| --- | --- |
| [后端源码解析](../../../packages/harness/shikigen/contracts/python_source.py) | 顶层入口允许 `FunctionDef` 和 `AsyncFunctionDef`；移除异步禁用分支，保留装饰器、签名和生成器检查；更新错误文案。 |
| [子进程执行器](../../../packages/harness/shikigen/tools/adapter/python_worker.py) | 运行时允许协程函数，显式拒绝 `inspect.isasyncgenfunction`；协程通过 `asyncio.run` 执行，取得最终值后继续校验严格 JSON。 |
| [前端源码分析](../../../frontend/src/python-source.ts) | 允许异步入口，保留其他入口限制；确认 `await` 不被误报，嵌套函数和生成器检查与后端保持一致。 |
| [工具表单](../../../frontend/src/components/tools/ToolDefinitionForm.tsx) | 更新只支持同步入口的帮助文案。 |
| [共享源码样例](../../../tests/fixtures/python_source_cases.json) | 将异步入口从拒绝用例改为接受用例，补充异步参数、默认表达式和异步生成器边界。 |
| [Python API 测试](../../../tests/test_python_tool_api.py) | 更新异步拒绝断言，增加真实子进程中的异步执行、异常、超时及兼容性验证。 |
| [现行执行说明](python-tool-execution.md) | 实施完成后更新同步入口约定，并链接本方案及实际验证结果。 |

## 执行器实现方向

保持现有加载、实际入口检查和参数绑定顺序。实际入口需满足 `inspect.isfunction(entry)`、名称为 `main`，且既不是普通生成器函数，也不是异步生成器函数。

完成输入绑定后，按声明的函数类型执行：

```python
import asyncio
import inspect

if inspect.iscoroutinefunction(entry):
    value = asyncio.run(entry(**inputs))
else:
    value = entry(**inputs)

strict_json(value)
```

以上仅是调用分支示意，完整实现仍需保留现有错误转换、返回大小限制和结果文件写入。

每次调用已有独立解释器，可以在子进程中为协程入口创建事件循环，不需要在后端主事件循环中直接运行用户代码。异步入口异常仍进入现有 `python_runtime` 错误处理，最终返回值不符合严格 JSON 时仍使用 `python_return`。

## 生命周期与兼容边界

父进程继续承担每次调用的执行预算、取消和子进程回收，异步入口无需另建一套超时机制。实现后必须验证超时或取消仍能结束本次 Python 子进程、保留可取得的调试输出并清理临时目录。既有实现不承诺清理用户代码启动的整个派生进程树，本次不扩展该范围。

工具必须在 `main` 返回前等待所有影响结果的任务。`asyncio.run` 会在退出时取消仍未完成的任务；它不提供跨调用持续运行的后台任务能力。工具适合用 `asyncio.gather` 或 `TaskGroup` 管理并发操作。

异步入口中直接调用同步阻塞客户端，仍会阻塞该子进程的事件循环。要获得内部 I/O 并发，需要使用异步客户端，或在适当场景下使用 `asyncio.to_thread`。

解析和保存阶段继续只做静态分析，不导入或执行用户代码，不求值注解、默认函数调用或其他动态表达式。异步支持不改变源码持久化、工具定义结构、返回协议或依赖安装方式。

## 示例

以下示例只使用标准库，演示两个独立操作并发执行，并等待全部结果后返回：

```python
import asyncio

async def query(value):
    await asyncio.sleep(0.1)
    return value

async def main(count: int, label: str = "订单"):
    quantity, title = await asyncio.gather(query(count), query(label))
    return {"count": quantity, "label": title}
```

实际网络工具可将 `query` 替换为环境中已安装的异步客户端调用。依赖仍由当前后端 Python 环境提供。

## 验收要求

1. 同步工具的保存、草稿测试和已保存执行保持兼容，原有错误码与 JSON 约束不变。
2. 异步入口能在前端正常分析、保存和测试；后端生成与同步同签名一致的参数结构。
3. 真实子进程执行至少经过一次 `await` 的入口，返回最终 JSON 值；验证参数绑定、默认值省略和 stdout/stderr。
4. 异步执行抛出业务异常时返回 `python_runtime`；返回非法 JSON 值时返回 `python_return`。
5. 普通生成器和异步生成器在静态解析及实际入口检查中均被拒绝；嵌套辅助生成器不被误认为入口生成器。
6. 解析与保存异步源码时不运行导入、注解或默认函数调用；沿用现有静态解析安全边界。
7. 异步入口超时或被取消时完成子进程回收与临时目录清理，保留可取得的退出信息和调试输出。
8. 同步 `main` 返回协程对象时仍明确失败，避免默默扩大入口协议。

实现时先更新共享样例和前端分析，再调整后端解析与执行器，最后运行相关前后端测试、类型检查和格式检查。并发测试应验证操作能共同推进，避免依赖容易抖动的精确耗时断言。

## 成本判断

这是局部功能扩展，主要成本在三处入口规则保持一致，以及真实子进程的生命周期回归。无需重构 Agent 调度或新增持久字段。初步估计熟悉项目后可在半天左右完成实现和针对性验证；若涉及新增依赖、后台任务或多工具调度，应单独扩大方案范围。
