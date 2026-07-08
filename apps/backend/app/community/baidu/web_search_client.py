from dataclasses import dataclass
import httpx
import os


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
                    error_message = f"Baidu API returned status {response.status_code}: {response.text}"
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


if __name__ == "__main__":
    import asyncio
    from dotenv import load_dotenv

    load_dotenv()

    async def _test():
        client = BaiduWebSearchClient()
        result = await client.fetch("什么是langchain？")
        print(result)

    asyncio.run(_test())
