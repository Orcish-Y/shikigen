from zoneinfo import ZoneInfo

from langchain.tools import tool


@tool
def get_current_time() -> str:
  """Get the current time."""
  import datetime

  now = datetime.datetime.now(ZoneInfo("Asia/Shanghai"))
  return now.strftime("%Y-%m-%d %H:%M:%S")
