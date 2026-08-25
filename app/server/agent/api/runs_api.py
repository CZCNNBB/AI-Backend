from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.common.db.postgres_db import get_postgres_engine
from app.common.schemas.result import Result
from app.server.agent.src.runs import AgentRunService
from app.server.agent.src.runs.schemas import (
    AgentRunChainRequest,
    AgentRunChainResponse,
    AgentRunDetailRequest,
    AgentRunSearchRequest,
    AgentRunSearchResponse,
    AgentRunView,
)


router = APIRouter(prefix="/runs")
run_service = AgentRunService()


@router.post("/search", response_model=Result[AgentRunSearchResponse], summary="查询 Agent 运行记录列表")
def search_agent_runs(
    request: AgentRunSearchRequest,
    db: Session = Depends(get_postgres_engine),
):
    """分页查询 Agent 运行记录。

    Args:
        request: 运行记录查询条件和分页参数。
        db: PostgreSQL 数据库会话。

    Returns:
        统一响应结构，data 中包含分页运行记录。
    """
    result = run_service.search_runs(db, request)
    return Result.success(result)


@router.post("/detail", response_model=Result[AgentRunView | None], summary="查询 Agent 运行记录详情")
def get_agent_run_detail(
    request: AgentRunDetailRequest,
    db: Session = Depends(get_postgres_engine),
):
    """根据 run_id 查询单条 Agent 运行记录详情。

    Args:
        request: 运行记录详情查询参数。
        db: PostgreSQL 数据库会话。

    Returns:
        统一响应结构，data 中包含匹配到的运行记录；不存在时 data 为 None。
    """
    result = run_service.get_run_view(db, request.run_id)
    return Result.success(result)


@router.post("/chain", response_model=Result[AgentRunChainResponse], summary="查询 Agent 主子运行链路")
def get_agent_run_chain(
    request: AgentRunChainRequest,
    db: Session = Depends(get_postgres_engine),
):
    """查询某次主 Agent 运行及其触发的子 Agent 运行链路。

    Args:
        request: 主 Agent 运行 ID。
        db: PostgreSQL 数据库会话。

    Returns:
        统一响应结构，data 中包含主运行和子运行记录。
    """
    items = run_service.list_run_chain(db, request.run_id)
    return Result.success(AgentRunChainResponse(run_id=request.run_id, items=items))