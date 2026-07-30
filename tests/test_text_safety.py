import unittest

from openai._utils._json import openapi_dumps

from text_safety import replace_surrogates


class ReplaceSurrogatesTests(unittest.TestCase):
  def test_makes_surrogateescape_text_json_encodable(self) -> None:
    unsafe = "bad: \udce9"

    safe = replace_surrogates(unsafe)

    self.assertEqual(safe, "bad: \ufffd")
    openapi_dumps({"messages": [{"role": "user", "content": safe}]})

  def test_preserves_valid_utf8_text(self) -> None:
    self.assertEqual(replace_surrogates("你好，柔爪"), "你好，柔爪")
