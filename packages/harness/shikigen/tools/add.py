from langchain.tools import tool


@tool
def add(a: float, b: float) -> float:
  """Add two numbers together."""
  return a + b
