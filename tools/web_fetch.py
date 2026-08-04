import asyncio
import logging
import os

import httpx
from langchain.tools import tool

from utils.readability import HtmlReadabilityExtractor

logger = logging.getLogger(__name__)

html_readability_extractor = HtmlReadabilityExtractor()


class JinaClient:
  def __init__(self):
    self.api_key = os.getenv("JINA_API_KEY")
    self.proxy = os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY")

  async def fetch(
    self, url: str, return_format: str = "html", timeout: int = 300
  ) -> str:
    headers = {
      "Content-Type": "application/json",
      "x-Return-Format": return_format,
      "x-Timeout": str(timeout),
    }

    if self.api_key:
      headers["Authorization"] = f"Bearer {self.api_key}"

    try:
      async with httpx.AsyncClient() as client:
        data = {"url": url}
        response: httpx.Response = await client.post(
          "https://r.jina.ai/", headers=headers, json=data, timeout=timeout
        )
        if response.status_code != 200:
          error_message = (
            f"Jina Api returned status {response.status_code}: {response.text}"
          )
          logger.error(error_message)
          return f"Error: {error_message}"

        if not response.text or not response.text.strip():
          error_message = "Jina Api returned empty response"
          logger.error(error_message)
          return f"Error: {error_message}"

        return response.text
    except Exception as e:
      error_message = f"Request to Jina Api failed: {type(e).__name__}: {e}"
      logger.warning(error_message)
      return f"Error: {error_message}"


jina_client = JinaClient()


@tool("web_fetch", parse_docstring=True)
async def web_fetch_tool(url: str) -> str:
  """Fetch the contents of a web page at a given URL.
  Only fetch EXACT URLs that have been provided directly by the user or have been returned in results from the web_search and web_fetch tools.
  This tool can NOT access content that requires authentication, such as private Google Docs or pages behind login walls.
  Do NOT add www. to URLs that do NOT have them.
  URLs must include the schema: https://example.com is a valid URL while example.com is an invalid URL.

  Args:
      url: The URL to fetch the contents of.
  """

  html_content = await jina_client.fetch(url)
  article = await asyncio.to_thread(
    html_readability_extractor.extract_article, html_content
  )
  return article.to_markdown()
