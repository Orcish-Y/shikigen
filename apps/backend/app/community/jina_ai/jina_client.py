import httpx  
import logging

logger = logging.getLogger(__name__)

class JinaClient:  
  async def fetch(self, url: str, return_format: str = 'html', timeout: int = 300) -> str:
    headers = {
      "Content-Type": "application/json",
      'x-Return-Format': return_format,
      'x-Timeout': str(timeout),
    }

    # 注入 api key

    try:
      async with httpx.AsyncClient() as client:
          data = {"url": url}
          response: httpx.Response = await client.post("https://r.jina.ai/", headers=headers, json=data, timeout=timeout)
          if response.status_code != 200:
            error_message = f'Jina Api returned status {response.status_code}: {response.text}'
            logger.error(error_message)
            return f"Error: {error_message}"

          if not response.text or not response.text.strip():
            error_message = f'Jina Api returned empty response'
            logger.error(error_message)
            return f"Error: {error_message}"

          return response.text
    except Exception as e:
      error_message = f"Request to Jina Api failed: {type(e).__name__}: {e}"
      logger.warning(error_message)
      return f"Error: {error_message}"