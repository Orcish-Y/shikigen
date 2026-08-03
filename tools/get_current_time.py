from langchain.tools import tool


@tool
def get_current_time() -> str:
  """Get the current time."""
  import datetime
  from zoneinfo import ZoneInfo

  now = datetime.datetime.now(ZoneInfo("Asia/Shanghai"))
  return now.strftime("%Y-%m-%d %H:%M:%S")
