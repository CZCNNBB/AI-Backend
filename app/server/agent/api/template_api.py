from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.common.db.postgres_db import get_postgres_engine
from app.common.schemas.result import Result
from app.server.agent.src.templates import AgentTemplateService
from app.server.agent.src.templates.schemas import (
    AgentTemplateDeleteRequest,
    AgentTemplateDetailRequest,
    AgentTemplateSearchRequest,
    AgentTemplateSearchResponse,
    AgentTemplateUpsertRequest,
    AgentTemplateView,
)


router = APIRouter(prefix="/templates")
template_service = AgentTemplateService()


@router.post("/upsert", response_model=Result[AgentTemplateView], summary="创建或更新 Agent 模板")
def upsert_agent_template(
    request: AgentTemplateUpsertRequest,
    db: Session = Depends(get_postgres_engine),
):
    """
    创建或更新 Agent 模板。

    Args:
        request: 模板创建或更新参数。
        db: PostgreSQL 数据库会话。

    Returns:
        统一响应结构，data 中包含保存后的模板信息。
    """
    result = template_service.upsert_template(db, request)
    return Result.success(result)


@router.post("/detail", response_model=Result[AgentTemplateView | None], summary="查询 Agent 模板详情")
def get_agent_template_detail(
    request: AgentTemplateDetailRequest,
    db: Session = Depends(get_postgres_engine),
):
    """
    根据 agent_id 查询 Agent 模板详情。

    Args:
        request: 模板详情查询参数。
        db: PostgreSQL 数据库会话。

    Returns:
        统一响应结构，data 中包含模板详情；不存在时 data 为 null。
    """
    result = template_service.get_template(db, request.agent_id)
    return Result.success(result)


@router.post("/search", response_model=Result[AgentTemplateSearchResponse], summary="查询 Agent 模板列表")
def search_agent_templates(
    request: AgentTemplateSearchRequest,
    db: Session = Depends(get_postgres_engine),
):
    """
    分页查询 Agent 模板列表。

    Args:
        request: 模板分页查询参数。
        db: PostgreSQL 数据库会话。

    Returns:
        统一响应结构，data 中包含分页模板列表。
    """
    result = template_service.search_templates(db, request)
    return Result.success(result)


@router.post("/delete", response_model=Result[int], summary="批量删除 Agent 模板")
def delete_agent_templates(
    request: AgentTemplateDeleteRequest,
    db: Session = Depends(get_postgres_engine),
):
    """
    根据 agent_id 列表批量删除 Agent 模板。

    Args:
        request: 批量删除参数，包含待删除的 agent_id 列表。
        db: PostgreSQL 数据库会话。

    Returns:
        统一响应结构，data 中包含实际删除的模板数量。
    """
    deleted = template_service.delete_templates(db, request)
    return Result.success(deleted)
