from langchain.chat_models import BaseChatModel, init_chat_model

from harness.app_config import ModelConfig


def create_chat_model(config: ModelConfig) -> BaseChatModel:
  """Create a LangChain chat model from validated application configuration."""
  model_options = {"base_url": config.base_url} if config.base_url is not None else {}
  return init_chat_model(
    config.default,
    model_provider=config.provider,
    **model_options,
  )
