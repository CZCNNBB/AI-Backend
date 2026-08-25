from datetime import datetime

from sqlalchemy import func
from sqlmodel import Session, select

from app.server.agent.src.context.models import AgentConversation, AgentMessage


class AgentContextRepository:
    """Agent 上下文数据访问层，负责读写 agent schema 下的历史表。"""

    def get_conversation(self, db: Session, conversation_id: str) -> AgentConversation | None:
        """
        根据 conversation_id 查询会话。

        Args:
            db: 数据库会话。
            conversation_id: 业务会话 ID。

        Returns:
            匹配到的会话记录；不存在时返回 None。
        """
        sql = select(AgentConversation).where(AgentConversation.conversation_id == conversation_id)
        return db.exec(sql).first()

    def create_conversation(self, db: Session, conversation: AgentConversation) -> AgentConversation:
        """
        创建 Agent 会话记录。

        Args:
            db: 数据库会话。
            conversation: 待保存的会话模型。

        Returns:
            已持久化的会话模型。
        """
        db.add(conversation)
        db.commit()
        db.refresh(conversation)
        return conversation

    def touch_conversation(self, db: Session, conversation: AgentConversation) -> AgentConversation:
        """
        更新会话的 updated_at，用于标记最近一次活跃时间。

        Args:
            db: 数据库会话。
            conversation: 已存在的会话模型。

        Returns:
            更新后的会话模型。
        """
        conversation.updated_at = datetime.now()
        db.add(conversation)
        db.commit()
        db.refresh(conversation)
        return conversation

    def create_message(self, db: Session, message: AgentMessage) -> AgentMessage:
        """
        创建一条 Agent 历史消息。

        Args:
            db: 数据库会话。
            message: 待保存的消息模型。

        Returns:
            已持久化的消息模型。
        """
        db.add(message)
        db.commit()
        db.refresh(message)
        return message

    def list_conversations(
        self,
        db: Session,
        *,
        conversation_id: str,
    ) -> tuple[list[AgentConversation], int]:
        """
        根据 conversation_id 查询 Agent 会话。

        Args:
            db: 数据库会话。
            conversation_id: 会话 ID，精确匹配。

        Returns:
            会话列表和总数量。这里保持列表结构，是为了 API 响应结构后续扩展时更稳定。
        """
        base_sql = select(AgentConversation).where(AgentConversation.conversation_id == conversation_id)
        count_sql = select(func.count()).select_from(AgentConversation).where(AgentConversation.conversation_id == conversation_id)
        list_sql = base_sql.order_by(AgentConversation.updated_at.desc()).limit(1)
        rows = list(db.exec(list_sql).all())
        total = db.exec(count_sql).one()
        return rows, int(total)

    def list_recent_messages(self, db: Session, conversation_id: str, limit: int = 20) -> list[AgentMessage]:
        """
        查询某个会话最近的历史消息，并按时间正序返回。

        Args:
            db: 数据库会话。
            conversation_id: 会话 ID。
            limit: 最多返回多少条消息。

        Returns:
            最近消息列表，顺序为从旧到新，方便直接拼装到模型上下文。
        """
        # 先按 id 倒序取最近 N 条，避免大表扫描过多历史消息。
        latest_sql = (
            select(AgentMessage)
            .where(AgentMessage.conversation_id == conversation_id)
            .order_by(AgentMessage.id.desc())
            .limit(limit)
        )
        latest_messages = list(db.exec(latest_sql).all())

        # 模型输入需要按真实对话顺序排列，所以这里再翻转成从旧到新。
        return list(reversed(latest_messages))
