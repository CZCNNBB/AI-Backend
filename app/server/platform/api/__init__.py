"""业务平台管理 API 聚合入口。"""

from fastapi import APIRouter

from app.server.platform.api.platform_api import router as platform_router


router = APIRouter()
router.include_router(platform_router)

__all__ = ["router"]
