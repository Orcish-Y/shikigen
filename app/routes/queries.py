"""JSON 事实查询的 HTTP 错误及缓存策略。"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import HTTPException, Response
from shikigen.contracts.runs import QueryUnavailable, RunNotFound, ThreadNotFound
from shikigen.contracts.threads import InvalidThreadCursor

logger = logging.getLogger(__name__)
_QUERY_RESPONSE_HEADERS = {"Cache-Control": "no-store"}


def apply_query_response_headers(response: Response) -> None:
  """为事实查询响应应用统一缓存策略，不处理异常。"""
  response.headers.update(_QUERY_RESPONSE_HEADERS)


@contextmanager
def query_response_policy(response: Response) -> Iterator[None]:
  apply_query_response_headers(response)
  headers = _QUERY_RESPONSE_HEADERS.copy()
  try:
    yield
  except InvalidThreadCursor as error:
    raise HTTPException(422, str(error), headers=headers) from error
  except (RunNotFound, ThreadNotFound) as error:
    raise HTTPException(404, str(error), headers=headers) from error
  except QueryUnavailable as error:
    raise HTTPException(
      503, str(error), headers={**headers, "Retry-After": "1"}
    ) from error
  except Exception as error:
    logger.exception("committed_query_failed")
    raise HTTPException(
      500, "Unable to read committed facts", headers=headers
    ) from error
