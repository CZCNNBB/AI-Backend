from datetime import datetime
from typing import Any

from sqlalchemy import Column, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


def now_time() -> datetime:
    """返回当前时间，用于 Agent 上下文表的默认时间字段。"""
    return datetime.now()


class AgentConversation(SQLModel, table=True):
    """Agent 会话表模型，对应 agent.agent_conversations。"""

    __tablename__ = "agent_conversations"
    __table_args__ = {"schema": "agent"}

    id: int | None = Field(default=None, primary_key=True)
    conversation_id: str = Field(max_length=100, unique=True)
    title: str | None = Field(default=None, max_length=255)

    status: str = Field(default="active", max_length=30)

    extra_metadata: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column("metadata", JSONB, nullable=False),
    )

    created_at: datetime = Field(default_factory=now_time)
    updated_at: datetime = Field(default_factory=now_time)


class AgentMessage(SQLModel, table=True):
    """Agent 消息表模型，对应 agent.agent_messages。"""

    __tablename__ = "agent_messages"
    __table_args__ = {"schema": "agent"}

    id: int | None = Field(default=None, primary_key=True)
    conversation_id: str = Field(
        sa_column=Column(
            String(100),
            ForeignKey("agent.agent_conversations.conversation_id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    message_id: str = Field(max_length=100, unique=True)

    parent_message_id: str | None = Field(default=None, max_length=100)

    role: str = Field(max_length=50)
    message_type: str = Field(max_length=50)

    content: str | None = Field(default=None)
    structured_content: dict[str, Any] | None = Field(default=None, sa_column=Column(JSONB))
    tool_name: str | None = Field(default=None, max_length=100)
    tool_call_id: str | None = Field(default=None, max_length=100)

    status: str = Field(default="success", max_length=30)
    error_message: str | None = Field(default=None)

    extra_metadata: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column("metadata", JSONB, nullable=False),
    )

    created_at: datetime = Field(default_factory=now_time)
