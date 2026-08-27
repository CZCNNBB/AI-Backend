from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.common.db.postgres_db import get_postgres_engine
from app.common.schemas.result import Result
from app.server.agent.src.context import AgentContextService
from app.server.agent.src.context.schemas import (
    AgentConversationMessagesRequest,
    AgentConversationMessagesResponse,
    AgentConversationSearchRequest,
    AgentConversationSearchResponse,
)
from app.server.platform.src import PlatformPrincipal, get_platform_principal


router = APIRouter(prefix="/conversations")
context_service = AgentContextService()


@router.post("/search", response_model=Result[AgentConversationSearchResponse], summary="查询 Agent 会话列表")
def search_agent_conversations(
    request: AgentConversationSearchRequest,
    principal: PlatformPrincipal = Depends(get_platform_principal),
    db: Session = Depends(get_postgres_engine),
):
    """
    根据 conversation_id 查询 Agent 会话。

    Args:
        request: 会话查询参数，只支持按 conversation_id 精确查询。
        db: PostgreSQL 数据库会话。

    Returns:
        统一响应结构，data 中包含匹配到的会话信息。
    """
    result = context_service.search_conversations(
        db,
        platform_id=principal.platform_id,
        request=request,
    )
    return Result.success(result)


@router.post("/messages", response_model=Result[AgentConversationMessagesResponse], summary="查询 Agent 会话消息")
def list_agent_conversation_messages(
    request: AgentConversationMessagesRequest,
    principal: PlatformPrincipal = Depends(get_platform_principal),
    db: Session = Depends(get_postgres_engine),
):
    """
    根据 conversation_id 查询某条会话的历史消息。

    Args:
        request: 消息查询参数，必须传 conversation_id。
        db: PostgreSQL 数据库会话。

    Returns:
        统一响应结构，data 中包含该会话最近的历史消息。
    """
    messages = context_service.get_recent_messages(
        db,
        platform_id=principal.platform_id,
        external_user_id=request.external_user_id,
        conversation_id=request.conversation_id,
        limit=request.limit,
    )
    return Result.success(
        AgentConversationMessagesResponse(
            conversation_id=request.conversation_id,
            messages=messages,
        )
    )
