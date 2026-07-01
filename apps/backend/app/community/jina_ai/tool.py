import asyncio
from app.community.jina_ai.jina_client import JinaClient
from langchain.tools import tool
from app.utils.readability import HtmlReadabilityExtractor

html_readability_extractor = HtmlReadabilityExtractor()
@tool("web_fetch")
async def web_fetch_tool(url: str) -> str:
  jina_client = JinaClient()
  html_content = await jina_client.fetch(url)
  print(html_content)
  article = await asyncio.to_thread(html_readability_extractor.extract_article, html_content)

  return article.to_markdown()