"""JSON 事实查询的 HTTP 错误及缓存策略。"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import HTTPException, Response
from shikigen.contracts.runs import QueryUnavailable, RunNotFound, ThreadNotFound

logger = logging.getLogger(__name__)


@contextmanager
def query_response_policy(response: Response) -> Iterator[None]:
  headers = {"Cache-Control": "no-store"}
  response.headers.update(headers)
  try:
    yield
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
