"""业务平台及平台 API Key 管理接口。"""

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.common.db.postgres_db import get_postgres_engine
from app.common.schemas.result import Result
from app.server.platform.src.schemas import (
    AgentPlatformAccessOption,
    AgentPlatformAccessRequest,
    BusinessPlatformAPIKeyCreateRequest,
    BusinessPlatformAPIKeyCreateResponse,
    BusinessPlatformAPIKeyDisableRequest,
    BusinessPlatformAPIKeyListRequest,
    BusinessPlatformAPIKeyView,
    BusinessPlatformDetailRequest,
    BusinessPlatformSearchRequest,
    BusinessPlatformSearchResponse,
    BusinessPlatformUpsertRequest,
    BusinessPlatformView,
)
from app.server.platform.src.service import BusinessPlatformService


router = APIRouter(prefix="/platforms")
platform_service = BusinessPlatformService()


@router.post("/upsert", response_model=Result[BusinessPlatformView], summary="创建或更新业务平台")
def upsert_business_platform(
    request: BusinessPlatformUpsertRequest,
    db: Session = Depends(get_postgres_engine),
):
    """创建或更新业务平台基础信息。"""
    return Result.success(platform_service.upsert_platform(db, request))


@router.post("/detail", response_model=Result[BusinessPlatformView | None], summary="查询业务平台详情")
def get_business_platform_detail(
    request: BusinessPlatformDetailRequest,
    db: Session = Depends(get_postgres_engine),
):
    """根据平台编码查询业务平台详情。"""
    return Result.success(platform_service.get_platform(db, request.platform_code))


@router.post("/search", response_model=Result[BusinessPlatformSearchResponse], summary="查询业务平台列表")
def search_business_platforms(
    request: BusinessPlatformSearchRequest,
    db: Session = Depends(get_postgres_engine),
):
    """分页查询业务平台。"""
    return Result.success(platform_service.search_platforms(db, request))


@router.post(
    "/agent-access-options",
    response_model=Result[list[AgentPlatformAccessOption]],
    summary="查询 Agent 关联平台和调试 API Key",
)
def list_agent_platform_access_options(
    request: AgentPlatformAccessRequest,
    db: Session = Depends(get_postgres_engine),
):
    """供内网管理调用页按 Agent 自动选择业务平台和 API Key。"""
    return Result.success(platform_service.list_agent_platform_access_options(db, request))


@router.post(
    "/api-keys/create",
    response_model=Result[BusinessPlatformAPIKeyCreateResponse],
    summary="签发平台 API Key",
)
def create_business_platform_api_key(
    request: BusinessPlatformAPIKeyCreateRequest,
    db: Session = Depends(get_postgres_engine),
):
    """为指定业务平台签发并保存一个可供内网调试读取的 API Key。"""
    return Result.success(platform_service.create_api_key(db, request))


@router.post(
    "/api-keys/list",
    response_model=Result[list[BusinessPlatformAPIKeyView]],
    summary="查询平台 API Key 列表",
)
def list_business_platform_api_keys(
    request: BusinessPlatformAPIKeyListRequest,
    db: Session = Depends(get_postgres_engine),
):
    """查询指定平台全部 API Key，供公司内网管理页面查看和复制。"""
    return Result.success(platform_service.list_api_keys(db, request))


@router.post("/api-keys/disable", response_model=Result[bool], summary="停用平台 API Key")
def disable_business_platform_api_key(
    request: BusinessPlatformAPIKeyDisableRequest,
    db: Session = Depends(get_postgres_engine),
):
    """按照 API Key 记录 ID 停用凭证。"""
    platform_service.disable_api_key(db, request)
    return Result.success(True)
