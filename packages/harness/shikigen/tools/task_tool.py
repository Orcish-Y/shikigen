import logging
from typing import Literal

from langchain.agents import create_agent
from langchain.messages import HumanMessage
from langchain.tools import tool
from langchain_core.tools import BaseTool

from shikigen.app_config import SubagentConfig, SubagentsConfig
from shikigen.tools.tool_registry import ToolRegistry

logger = logging.getLogger(__name__)


def _select_tools(
  registry: ToolRegistry, config: SubagentConfig, agent_type: str
) -> list[BaseTool]:
  configured = set(config.tools or []) | set(config.disallowed_tools)
  missing = configured - set(registry.names)
  if missing:
    logger.warning("Subagent %s: unavailable tools: %s", agent_type, sorted(missing))
  allowed = None if config.tools is None else set(config.tools)
  denied = set(config.disallowed_tools) | {"task"}
  selected = [
    t
    for t in registry.list()
    if (allowed is None or t.name in allowed) and t.name not in denied
  ]
  logger.info("Subagent %s tools: %s", agent_type, [t.name for t in selected])
  return selected


BASH_AGENT_PROMPT = """\
你是一个专注于工作区文件和命令行任务的子 Agent。主 Agent 会给你一项明确的委派任务，
你只负责完成这项任务，并把结果返回给主 Agent。

工作原则：
- 先检查相关文件、目录和当前状态，再决定要执行的命令；不要凭猜测操作。
- 仅在当前工作区内工作，使用提供的工具读取、搜索、修改文件或执行命令。
- 选择范围最小、可复现的命令；避免破坏性命令，不要删除或覆盖无关内容。
- 尊重工作区中已有的修改，不要擅自还原、重写或整理与任务无关的代码。
- 修改后尽可能运行针对性的检查或测试；如果无法验证，要明确说明原因。
- 遇到缺少信息、工具受限或命令失败时，先做安全的排查，再如实报告阻碍，
  不要伪造结果。

最终回复应简洁说明：完成了什么、涉及哪些文件或命令、验证结果，以及仍存在的风险或阻碍。
不要向最终用户说话，也不要扩展主 Agent 委派任务的范围。
"""


GENERAL_AGENT_PROMPT = """\
你是一个通用任务子 Agent。主 Agent 会给你一项明确的委派任务，你需要独立分析、使用合适的
工具完成任务，并把可靠、可核验的结果返回给主 Agent。

工作原则：
- 紧扣委派任务，先理解目标和已有上下文，再采取行动；不要处理无关事项。
- 按需选择工具并优先核实事实。涉及代码或文件时，先检查现状，修改后尽可能验证。
- 将重要结论建立在工具输出或明确证据上；区分事实、推断和不确定信息。
- 尊重已有文件和修改，不做破坏性操作，不擅自扩大权限、范围或对外产生副作用。
- 遇到信息不足或工具受限时，完成仍可安全完成的部分，并明确报告阻碍；不要猜测或伪造。
- 不要把任务再次委派，也不要等待主 Agent 逐步指导；在现有范围内自主推进到可交付状态。

最终回复应直接给出结论，并简洁说明完成内容、关键证据或验证结果，以及仍存在的风险或阻碍。
不要向最终用户说话；你的回复将由主 Agent 汇总。
"""


def build_task_tool(
  model, tool_registry: ToolRegistry, *, subagents: SubagentsConfig | None = None
):
  config = subagents if subagents is not None else SubagentsConfig()
  tools_by_type = {
    "general": _select_tools(tool_registry, config.general, "general"),
    "bash": _select_tools(tool_registry, config.bash, "bash"),
  }

  def _create_subagent(agent_type: Literal["general", "bash"]):
    tools = tools_by_type[agent_type]
    prompt = BASH_AGENT_PROMPT if agent_type == "bash" else GENERAL_AGENT_PROMPT
    available = ", ".join(tool.name for tool in tools) or "无"
    prompt += (
      f"\n本次实际可用工具：{available}。\n"
      "类型名称不代表额外权限；仅使用本次提供的工具。"
      "没有工具时只能分析已有信息并回答；无法执行的操作应明确报告。\n"
    )
    return create_agent(model=model, tools=tools, system_prompt=prompt)

  @tool
  async def task(
    description: str,
    agent_type: Literal["general", "bash"] = "general",
  ) -> str:
    """将任务委派给子 Agent，等待执行完成后返回结果。

    Args:
        description: 要执行的子任务描述。越具体越好。
        agent_type: 子 Agent 类型。目前支持 "general"（应用配置的子工具集合）和
          "bash"（工作区任务）；两种类型的实际能力分别由应用配置决定。
    """
    sub_agent = _create_subagent(agent_type)
    result = await sub_agent.ainvoke({"messages": [HumanMessage(content=description)]})
    return result["messages"][-1].text

  return task
