from datetime import datetime
from typing import Any

from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


def now_time() -> datetime:
    """返回当前时间，用于 Agent 运行记录的默认时间字段。"""
    return datetime.now()


class AgentRun(SQLModel, table=True):
    """Agent 运行记录表模型，对应 agent.agent_runs。

    运行表只保留平台追踪真正需要的信息：
    - run_id 直接作为主键，代表一次 Agent 运行。
    - run_type 区分主 Agent 和 A2A 子 Agent。
    - parent_run_id 把子 Agent 挂回主 Agent。
    """

    __tablename__ = "agent_runs"
    __table_args__ = {"schema": "agent"}

    run_id: str = Field(max_length=100, primary_key=True)
    run_type: str = Field(default="main", max_length=30)
    parent_run_id: str | None = Field(default=None, max_length=100)

    agent_id: str | None = Field(default=None, max_length=100)
    conversation_id: str | None = Field(default=None, max_length=100)
    user_message_id: str | None = Field(default=None, max_length=100)
    assistant_message_id: str | None = Field(default=None, max_length=100)

    query: str | None = Field(default=None)
    answer: str | None = Field(default=None)

    status: str = Field(default="running", max_length=30)
    error_message: str | None = Field(default=None)
    elapsed_ms: float | None = Field(default=None)

    extra_metadata: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column("metadata", JSONB, nullable=False),
    )

    started_at: datetime = Field(default_factory=now_time)
    finished_at: datetime | None = Field(default=None)