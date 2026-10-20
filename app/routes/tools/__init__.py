"""工具管理路由的统一入口。"""

from fastapi import APIRouter

from . import definitions, mcp_connections

router = APIRouter()
router.include_router(definitions.router)
router.include_router(mcp_connections.router)
