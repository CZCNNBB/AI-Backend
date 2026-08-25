from datetime import datetime
from typing import Any

from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


def now_time() -> datetime:
    """返回当前时间，用作 MCP 工具表的默认时间字段。"""
    return datetime.now()


class AgentMCPToolRecord(SQLModel, table=True):
    """Agent MCP 工具配置表模型，对应 agent.agent_mcp_tools。

    一条记录代表一个可被 Agent 选择的 MCP 工具，服务地址、真实工具名和工具描述都直接放在同一张表中，
    这样前端和 Agent 运行时都只需要关心“工具”这个概念。
    """

    __tablename__ = "agent_mcp_tools"
    __table_args__ = {"schema": "agent"}

    id: int | None = Field(default=None, primary_key=True)
    mcp_code: str = Field(max_length=150, unique=True)
    name: str = Field(max_length=255)
    description: str | None = Field(default=None)

    base_url: str
    transport: str = Field(default="http", max_length=50)
    auth_type: str | None = Field(default=None, max_length=50)
    auth_config: dict[str, Any] | None = Field(default=None, sa_column=Column(JSONB, nullable=True))

    input_schema: dict[str, Any] | None = Field(default=None, sa_column=Column(JSONB, nullable=True))
    output_schema: dict[str, Any] | None = Field(default=None, sa_column=Column(JSONB, nullable=True))

    status: str = Field(default="enabled", max_length=30)
    created_at: datetime = Field(default_factory=now_time)
    updated_at: datetime = Field(default_factory=now_time)
