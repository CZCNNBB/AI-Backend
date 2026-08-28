from datetime import datetime
from typing import Any

from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


def now_time() -> datetime:
    """返回当前时间，用作 MCP 工具表的默认时间字段。"""
    return datetime.now()


class MCPToolRecord(SQLModel, table=True):
    """HTTP API 转换型 MCP 工具配置，对应 ``mcp.mcp_tools``。

    一条记录描述一个普通 HTTP Endpoint。平台启动时读取所有已启用记录，
    通过统一执行器动态注册为 FastMCP Tool，不为单个工具生成 Python 源文件。
    """

    __tablename__ = "mcp_tools"
    __table_args__ = {"schema": "mcp"}

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=150, unique=True)
    description: str | None = Field(default=None)

    api_url: str
    http_method: str = Field(default="POST", max_length=10)
    static_headers: dict[str, Any] | None = Field(default=None, sa_column=Column(JSONB, nullable=True))
    parameters: list[dict[str, Any]] | None = Field(default=None, sa_column=Column(JSONB, nullable=True))

    business_token_header: str | None = Field(default=None, max_length=150)
    input_schema: dict[str, Any] | None = Field(default=None, sa_column=Column(JSONB, nullable=True))
    output_schema: dict[str, Any] | None = Field(default=None, sa_column=Column(JSONB, nullable=True))

    timeout_seconds: float = Field(default=30.0)
    status: str = Field(default="draft", max_length=30)
    created_at: datetime = Field(default_factory=now_time)
    updated_at: datetime = Field(default_factory=now_time)
