import unittest
from unittest.mock import Mock, patch

from harness.app_config import ModelConfig
from harness.model import create_chat_model


class CreateChatModelTests(unittest.TestCase):
  def test_creates_model_from_validated_config(self) -> None:
    config = ModelConfig(
      default="configured-model",
      provider="configured-provider",
      base_url="https://models.example.com/v1",
    )
    configured_model = Mock()

    with patch(
      "harness.model.init_chat_model",
      return_value=configured_model,
    ) as init_model:
      model = create_chat_model(config)

    self.assertIs(model, configured_model)
    init_model.assert_called_once_with(
      "configured-model",
      model_provider="configured-provider",
      base_url="https://models.example.com/v1",
    )

  def test_omits_missing_base_url(self) -> None:
    config = ModelConfig(default="configured-model", provider="configured-provider")

    with patch("harness.model.init_chat_model") as init_model:
      create_chat_model(config)

    init_model.assert_called_once_with(
      "configured-model",
      model_provider="configured-provider",
    )


if __name__ == "__main__":
  unittest.main()
