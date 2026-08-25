from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.common.db.postgres_db import get_postgres_engine
from app.common.schemas.result import Result
from app.server.agent.src.model import ModelConfigService
from app.server.agent.src.model.schemas import (
    ModelConfigDeleteRequest,
    ModelConfigDetailRequest,
    ModelConfigSearchRequest,
    ModelConfigSearchResponse,
    ModelConfigUpsertRequest,
    ModelConfigView,
)


router = APIRouter(prefix="/models")
model_config_service = ModelConfigService()


@router.post("/upsert", response_model=Result[ModelConfigView], summary="新增或更新模型配置")
def upsert_model_config(
    request: ModelConfigUpsertRequest,
    db: Session = Depends(get_postgres_engine),
):
    """新增或更新平台模型配置。"""
    result = model_config_service.upsert_model(db, request)
    return Result.success(result)


@router.post("/detail", response_model=Result[ModelConfigView | None], summary="查询模型配置详情")
def get_model_config_detail(
    request: ModelConfigDetailRequest,
    db: Session = Depends(get_postgres_engine),
):
    """根据 model_code 查询模型配置详情。"""
    result = model_config_service.get_model(db, request.model_code)
    return Result.success(result)


@router.post("/search", response_model=Result[ModelConfigSearchResponse], summary="查询模型配置列表")
def search_model_configs(
    request: ModelConfigSearchRequest,
    db: Session = Depends(get_postgres_engine),
):
    """分页查询平台模型配置列表。"""
    result = model_config_service.search_models(db, request)
    return Result.success(result)


@router.post("/delete", response_model=Result[int], summary="批量删除模型配置")
def delete_model_configs(
    request: ModelConfigDeleteRequest,
    db: Session = Depends(get_postgres_engine),
):
    """根据 model_code 列表批量删除模型配置。"""
    deleted = model_config_service.delete_models(db, request)
    return Result.success(deleted)
