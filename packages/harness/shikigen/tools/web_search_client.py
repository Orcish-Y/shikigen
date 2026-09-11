import os
from dataclasses import dataclass

import httpx
from langchain.tools import tool


@dataclass
class BaiduWebSearchResponse:
  content: str
  date: str
  icon: str | None
  id: int
  snippet: str | None
  title: str
  type: str
  url: str


def format_results(response_json: list[BaiduWebSearchResponse] | str) -> str:
  """从百度 API 响应中提取关键字段，格式化为 LLM 友好的文本。"""
  if isinstance(response_json, str):
    return response_json

  if not response_json:
    return "未找到相关搜索结果。"

  lines = ["## 搜索结果"]
  for i, doc in enumerate(response_json, 1):
    title = doc.title or "无标题"
    url = doc.url or ""
    # 优先用 abs(摘要)，如果没有则用 content 截断
    snippet = doc.snippet or doc.content or ""
    if len(snippet) > 2000:
      snippet = snippet[:2000] + "..."

    lines.append(f"### {i}. {title}")
    lines.append(f"- URL: {url}")
    lines.append(f"- {snippet}")
    lines.append("")

  return "".join(lines)


class BaiduWebSearchClient:
  def __init__(self):
    self.api_key = os.getenv("BAIDU_API_KEY")

  async def fetch(
    self, search_keyword: str, topk: int = 5
  ) -> list[BaiduWebSearchResponse] | str:
    headers = {
      "Content-Type": "application/json",
      "Authorization": f"Bearer {self.api_key}",
    }

    if not self.api_key:
      return "Error: Baidu API key is not set."

    try:
      async with httpx.AsyncClient() as client:
        data = {
          "messages": [{"content": search_keyword, "role": "user"}],
          "search_source": "baidu_search_v2",
          "resource_type_filter": [{"type": "web", "top_k": topk}],
        }

        response: httpx.Response = await client.post(
          "https://qianfan.baidubce.com/v2/ai_search/web_search",
          headers=headers,
          json=data,
        )

        if response.status_code != 200:
          error_message = (
            f"Baidu API returned status {response.status_code}: {response.text}"
          )
          return f"Error: {error_message}"

        response_json = response.json()

        references = response_json.get("references")
        if not references:
          return "未找到相关搜索结果。"

        fields = BaiduWebSearchResponse.__dataclass_fields__
        return [
          BaiduWebSearchResponse(**{k: v for k, v in ref.items() if k in fields})
          for ref in references
        ]

    except Exception as e:
      error_message = f"Request to Baidu API failed: {type(e).__name__}: {e}"
      return f"Error: {error_message}"


@tool("web_search")
async def web_search_tool(search_keyword: str, topk: int = 5) -> str:
  """Search the web for a given keyword and return the top 5 results.

  Args:
      search_keyword: The keyword to search for.
      topk: The number of top results to return.
  """

  baidu_client = BaiduWebSearchClient()
  search_results = await baidu_client.fetch(search_keyword, topk=topk)

  if isinstance(search_results, str) and search_results.startswith("Error:"):
    return search_results

  return format_results(search_results)


if __name__ == "__main__":
  import asyncio

  from dotenv import load_dotenv

  load_dotenv()

  async def _test():
    client = BaiduWebSearchClient()
    result = await client.fetch("什么是langchain？")
    print(result)

  asyncio.run(_test())
