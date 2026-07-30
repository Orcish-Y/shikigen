"""Helpers for keeping text safe to send as UTF-8 JSON."""


def replace_surrogates(text: str) -> str:
  """Replace byte-surrogates produced by ``surrogateescape``.

  ``input()`` may yield these when a terminal sends bytes that are not valid
  UTF-8.  They cannot be encoded by the OpenAI-compatible client.
  """
  return text.encode("utf-8", errors="surrogateescape").decode(
    "utf-8", errors="replace"
  )
