"""MCP Platform API 聚合入口。"""

from fastapi import APIRouter

from app.server.fastmcp.api.tool_api import router as tool_router


router = APIRouter()

# MCP Platform 的管理接口统一从此处聚合，main.py 只挂载一个模块路由。
router.include_router(tool_router)


__all__ = ["router"]
