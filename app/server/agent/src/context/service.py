from uuid import uuid4

from sqlmodel import Session

from app.common.core.exceptions import BusinessException
from app.server.agent.src.context.models import AgentConversation, AgentMessage
from app.server.agent.src.context.repository import AgentContextRepository
from app.server.agent.src.context.schemas import (
    AgentConversationSearchRequest,
    AgentConversationSearchResponse,
    AgentConversationView,
    ContextMessageCreate,
    ContextMessageView,
)


class AgentContextService:
    """Agent 历史上下文服务，负责会话创建、消息写入和上下文读取。"""

    def __init__(self, repository: AgentContextRepository | None = None):
        """
        初始化 Agent 历史上下文服务。

        Args:
            repository: Agent 上下文数据访问层，默认使用 PostgreSQL 实现。
        """
        self.repository = repository or AgentContextRepository()

    def ensure_conversation(
        self,
        db: Session,
        *,
        platform_id: int,
        external_user_id: str,
        agent_id: str,
        conversation_id: str,
        title: str | None = None,
        metadata: dict | None = None,
    ) -> AgentConversation:
        """
        确保会话存在；不存在则创建，存在则刷新活跃时间。

        Args:
            db: 数据库会话。
            agent_id: 创建或继续该会话的 Agent 模板 ID。
            conversation_id: 会话 ID。
            title: 会话标题。
            metadata: 会话扩展元数据。

        Returns:
            已存在或新创建的会话记录。
        """
        conversation = self.repository.get_conversation(
            db,
            platform_id=platform_id,
            external_user_id=external_user_id,
            conversation_id=conversation_id,
        )
        if conversation:
            if conversation.agent_id != agent_id:
                # 同一个 conversation_id 对应一份 Checkpoint 状态，不能更换 Agent 后继续使用。
                raise BusinessException(
                    code=409,
                    msg=(
                        f"会话 {conversation_id} 属于 Agent {conversation.agent_id}，"
                        f"不能使用 Agent {agent_id} 继续执行"
                    ),
                )
            return self.repository.touch_conversation(db, conversation)

        conversation = AgentConversation(
            conversation_id=conversation_id,
            platform_id=platform_id,
            external_user_id=external_user_id,
            agent_id=agent_id,
            title=title,
            extra_metadata=metadata or {},
        )
        return self.repository.create_conversation(db, conversation)

    def append_message(self, db: Session, payload: ContextMessageCreate) -> AgentMessage:
        """
        写入一条 Agent 历史消息。

        Args:
            db: 数据库会话。
            payload: 消息创建参数。

        Returns:
            已保存的消息记录。
        """
        message = AgentMessage(
            conversation_id=payload.conversation_id,
            message_id=payload.message_id or uuid4().hex,
            parent_message_id=payload.parent_message_id,
            role=payload.role,
            message_type=payload.message_type,
            content=payload.content,
            structured_content=payload.structured_content,
            tool_name=payload.tool_name,
            tool_call_id=payload.tool_call_id,
            status=payload.status,
            error_message=payload.error_message,
            extra_metadata=payload.metadata,
        )
        return self.repository.create_message(db, message)

    def add_user_message(self, db: Session, *, conversation_id: str, content: str, metadata: dict | None = None) -> AgentMessage:
        """
        写入用户消息。

        Args:
            db: 数据库会话。
            conversation_id: 会话 ID。
            content: 用户输入内容。
            metadata: 扩展元数据。

        Returns:
            已保存的用户消息。
        """
        return self.append_message(
            db,
            ContextMessageCreate(
                conversation_id=conversation_id,
                role="user",
                message_type="user_message",
                content=content,
                metadata=metadata or {},
            ),
        )

    def add_assistant_message(self, db: Session, *, conversation_id: str, content: str, metadata: dict | None = None) -> AgentMessage:
        """
        写入 Agent 最终回复消息。

        Args:
            db: 数据库会话。
            conversation_id: 会话 ID。
            content: Agent 回复内容。
            metadata: 扩展元数据。

        Returns:
            已保存的 Agent 回复消息。
        """
        return self.append_message(
            db,
            ContextMessageCreate(
                conversation_id=conversation_id,
                role="assistant",
                message_type="assistant_message",
                content=content,
                metadata=metadata or {},
            ),
        )

    def add_tool_call(
        self,
        db: Session,
        *,
        conversation_id: str,
        tool_name: str,
        tool_call_id: str | None = None,
        structured_content: dict | None = None,
        metadata: dict | None = None,
    ) -> AgentMessage:
        """
        写入工具调用记录。

        Args:
            db: 数据库会话。
            conversation_id: 会话 ID。
            tool_name: 工具名称。
            tool_call_id: 工具调用 ID。
            structured_content: 工具调用参数等结构化内容。
            metadata: 扩展元数据。

        Returns:
            已保存的工具调用消息。
        """
        return self.append_message(
            db,
            ContextMessageCreate(
                conversation_id=conversation_id,
                role="assistant",
                message_type="tool_call",
                content=None,
                structured_content=structured_content,
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                metadata=metadata or {},
            ),
        )

    def add_tool_result(
        self,
        db: Session,
        *,
        conversation_id: str,
        tool_name: str,
        content: str | None = None,
        tool_call_id: str | None = None,
        structured_content: dict | None = None,
        metadata: dict | None = None,
    ) -> AgentMessage:
        """
        写入工具执行结果记录。

        Args:
            db: 数据库会话。
            conversation_id: 会话 ID。
            tool_name: 工具名称。
            content: 工具返回的文本内容。
            tool_call_id: 工具调用 ID。
            structured_content: 工具返回的结构化内容。
            metadata: 扩展元数据。

        Returns:
            已保存的工具结果消息。
        """
        return self.append_message(
            db,
            ContextMessageCreate(
                conversation_id=conversation_id,
                role="tool",
                message_type="tool_result",
                content=content,
                structured_content=structured_content,
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                metadata=metadata or {},
            ),
        )

    def add_agent_event(
        self,
        db: Session,
        *,
        conversation_id: str,
        content: str | None = None,
        structured_content: dict | None = None,
        metadata: dict | None = None,
    ) -> AgentMessage:
        """
        写入 Agent 执行事件记录。

        Args:
            db: 数据库会话。
            conversation_id: 会话 ID。
            content: 事件文本说明。
            structured_content: 事件结构化数据。
            metadata: 扩展元数据。

        Returns:
            已保存的事件消息。
        """
        return self.append_message(
            db,
            ContextMessageCreate(
                conversation_id=conversation_id,
                role="agent",
                message_type="agent_event",
                content=content,
                structured_content=structured_content,
                metadata=metadata or {},
            ),
        )

    def add_reasoning_summary(self, db: Session, *, conversation_id: str, content: str, metadata: dict | None = None) -> AgentMessage:
        """
        写入模型推理摘要。

        注意：这里保存的是可审计的推理摘要，不保存模型隐藏思维链。

        Args:
            db: 数据库会话。
            conversation_id: 会话 ID。
            content: 推理摘要文本。
            metadata: 扩展元数据。

        Returns:
            已保存的推理摘要消息。
        """
        return self.append_message(
            db,
            ContextMessageCreate(
                conversation_id=conversation_id,
                role="assistant",
                message_type="reasoning_summary",
                content=content,
                metadata=metadata or {},
            ),
        )

    def add_error(
        self,
        db: Session,
        *,
        conversation_id: str,
        error_message: str,
        metadata: dict | None = None,
    ) -> AgentMessage:
        """
        写入 Agent 执行错误记录。

        Args:
            db: 数据库会话。
            conversation_id: 会话 ID。
            error_message: 错误信息。
            metadata: 扩展元数据。

        Returns:
            已保存的错误消息。
        """
        return self.append_message(
            db,
            ContextMessageCreate(
                conversation_id=conversation_id,
                role="agent",
                message_type="error",
                content=None,
                status="failed",
                error_message=error_message,
                metadata=metadata or {},
            ),
        )

    def get_recent_messages(
        self,
        db: Session,
        *,
        platform_id: int,
        external_user_id: str,
        conversation_id: str,
        limit: int = 20,
    ) -> list[ContextMessageView]:
        """
        查询最近历史消息。

        Args:
            db: 数据库会话。
            conversation_id: 会话 ID。
            limit: 最多返回多少条。

        Returns:
            历史消息视图列表。
        """
        messages = self.repository.list_recent_messages(
            db,
            platform_id=platform_id,
            external_user_id=external_user_id,
            conversation_id=conversation_id,
            limit=limit,
        )
        return [
            ContextMessageView(
                message_id=message.message_id,
                role=message.role,
                message_type=message.message_type,
                content=message.content,
                structured_content=message.structured_content,
                tool_name=message.tool_name,
                tool_call_id=message.tool_call_id,
                status=message.status,
                error_message=message.error_message,
                metadata=message.extra_metadata,
                created_at=message.created_at.isoformat() if message.created_at else None,
            )
            for message in messages
        ]

    def search_conversations(
        self,
        db: Session,
        *,
        platform_id: int,
        request: AgentConversationSearchRequest,
    ) -> AgentConversationSearchResponse:
        """
        分页查询 Agent 会话列表。

        Args:
            db: 数据库会话。
            request: 会话查询参数。

        Returns:
            会话分页查询结果。
        """
        rows, total = self.repository.list_conversations(
            db,
            platform_id=platform_id,
            external_user_id=request.external_user_id,
            agent_id=request.agent_id,
            conversation_id=request.conversation_id,
            page=request.page,
            page_size=request.page_size,
        )

        items = [
            AgentConversationView(
                conversation_id=row.conversation_id,
                external_user_id=row.external_user_id,
                agent_id=row.agent_id,
                title=row.title,
                status=row.status,
                metadata=row.extra_metadata,
                created_at=row.created_at.isoformat() if row.created_at else None,
                updated_at=row.updated_at.isoformat() if row.updated_at else None,
            )
            for row in rows
        ]

        return AgentConversationSearchResponse(
            total=total,
            page=request.page,
            page_size=request.page_size,
            items=items,
        )
