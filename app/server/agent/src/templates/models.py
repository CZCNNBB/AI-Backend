from datetime import datetime
from typing import Any

from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


def now_time() -> datetime:
    """返回当前时间，用作 Agent 模板表的默认时间字段。"""
    return datetime.now()


class AgentTemplate(SQLModel, table=True):
    """Agent 模板表模型，对应 agent.agent_templates。"""

    __tablename__ = "agent_templates"
    __table_args__ = {"schema": "agent"}

    id: int | None = Field(default=None, primary_key=True)
    agent_id: str = Field(max_length=100, unique=True)
    agent_name: str = Field(max_length=255)
    description: str | None = Field(default=None)

    config: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSONB, nullable=False))

    status: str = Field(default="active", max_length=30)
    created_at: datetime = Field(default_factory=now_time)
    updated_at: datetime = Field(default_factory=now_time)
