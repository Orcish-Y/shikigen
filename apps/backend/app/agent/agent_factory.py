from app.agent.middlewares.toolTtracking import ToolTtrackingMiddleware
from deepagents import create_deep_agent
from langchain_core.language_models import BaseChatModel


def create_agent(
    model: BaseChatModel | str,
):
    from app.agent.tools.registry import ToolRegistry
    from app.agent.tools.sync import ensure_sync_invocable

    tools = [ensure_sync_invocable(t) for t in ToolRegistry.tools]

    return create_deep_agent(
        model=model,
        tools=tools,
        middleware=[ToolTtrackingMiddleware()],
        # system_prompt=self.system_prompt,
        # skills=skill_names if skill_names else None,
        # backend=self._backend or StateBackend(),
        # checkpointer=self._checkpointer,
        # interrupt_on=self._interrupt_on,
    )
