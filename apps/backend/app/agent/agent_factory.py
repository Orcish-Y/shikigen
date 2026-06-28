from deepagents import create_deep_agent
from langchain_core.language_models import BaseChatModel


def create_agent(
    model: BaseChatModel,
):
    return create_deep_agent(
        model=model,
        # tools=extra_tools if extra_tools else None,
        # system_prompt=self.system_prompt,
        # skills=skill_names if skill_names else None,
        # backend=self._backend or StateBackend(),
        # checkpointer=self._checkpointer,
        # interrupt_on=self._interrupt_on,
    )
