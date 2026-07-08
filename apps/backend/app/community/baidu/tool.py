from app.community.baidu.web_search_client import BaiduWebSearchResponse
from langchain.tools import tool


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


@tool("web_search")
async def web_search_tool(search_keyword: str, topk: int = 5) -> str:
    """Search the web for a given keyword and return the top 5 results.

    Args:
        search_keyword: The keyword to search for.
        topk: The number of top results to return.
    """
    from app.community.baidu.web_search_client import BaiduWebSearchClient

    baidu_client = BaiduWebSearchClient()
    search_results = await baidu_client.fetch(search_keyword, topk=topk)

    if isinstance(search_results, str) and search_results.startswith("Error:"):
        return search_results

    return format_results(search_results)
