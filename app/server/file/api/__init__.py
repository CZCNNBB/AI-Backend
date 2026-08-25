from fastapi import APIRouter

from app.server.file.api.file_api import router as file_router


router = APIRouter()

# 文件服务 API 聚合出口。
router.include_router(file_router)


__all__ = ["router"]
