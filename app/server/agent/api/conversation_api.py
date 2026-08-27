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


@router.post(
    "/search",
    response_model=Result[AgentConversationSearchResponse],
    summary="根据外部用户 ID 查询 Agent 会话列表",
    description=(
        "查询当前 X-API-Key 所属业务平台中，指定 external_user_id 的会话列表。"
        "可以额外传入 agent_id，仅查询该用户与指定 Agent 的会话；"
        "也可以传入 conversation_id 对会话 ID 进行精确筛选。"
    ),
)
def search_agent_conversations(
    request: AgentConversationSearchRequest,
    principal: PlatformPrincipal = Depends(get_platform_principal),
    db: Session = Depends(get_postgres_engine),
):
    """
    根据外部业务用户 ID 查询其 Agent 会话列表。

    Args:
        request: 会话查询参数，external_user_id 必填，agent_id 和 conversation_id 可选。
        principal: 由 X-API-Key 解析得到的当前业务平台身份。
        db: PostgreSQL 数据库会话。

    Returns:
        统一响应结构，data 中包含当前业务平台、指定用户下匹配到的会话列表。
    """
    result = context_service.search_conversations(
        db,
        platform_id=principal.platform_id,
        request=request,
    )
    return Result.success(result)


@router.post(
    "/messages",
    response_model=Result[AgentConversationMessagesResponse],
    summary="根据会话 ID 查询详细消息历史",
    description=(
        "查询当前 X-API-Key 所属业务平台中，指定 external_user_id 和 conversation_id "
        "对应的会话消息历史。"
    ),
)
def list_agent_conversation_messages(
    request: AgentConversationMessagesRequest,
    principal: PlatformPrincipal = Depends(get_platform_principal),
    db: Session = Depends(get_postgres_engine),
):
    """
    根据 conversation_id 查询某条会话的历史消息。

    Args:
        request: 消息查询参数，必须传 external_user_id 和 conversation_id。
        principal: 由 X-API-Key 解析得到的当前业务平台身份。
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
