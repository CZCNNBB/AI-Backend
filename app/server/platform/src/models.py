"""业务平台、平台 API Key 和资源绑定的数据模型。"""

from datetime import datetime

from sqlalchemy import BigInteger, Column, ForeignKey, UniqueConstraint
from sqlmodel import Field, SQLModel


def now_time() -> datetime:
    """返回当前本地时间，用作平台相关表的默认时间。"""
    return datetime.now()


class BusinessPlatform(SQLModel, table=True):
    """业务平台表模型，对应 ``platform.business_platforms``。"""

    __tablename__ = "business_platforms"
    __table_args__ = {"schema": "platform"}

    id: int | None = Field(default=None, primary_key=True)
    platform_code: str = Field(max_length=100, unique=True)
    platform_name: str = Field(max_length=200)
    description: str | None = Field(default=None)
    status: str = Field(default="enabled", max_length=30)
    created_at: datetime = Field(default_factory=now_time)
    updated_at: datetime = Field(default_factory=now_time)


class BusinessPlatformAPIKey(SQLModel, table=True):
    """平台 API Key 表模型，内网模式同时保存明文和鉴权摘要。"""

    __tablename__ = "business_platform_api_keys"
    __table_args__ = (
        UniqueConstraint("platform_id", "key_name", name="uq_platform_api_keys_name"),
        {"schema": "platform"},
    )

    id: int | None = Field(default=None, primary_key=True)
    platform_id: int = Field(
        sa_column=Column(
            BigInteger,
            ForeignKey("platform.business_platforms.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    key_name: str = Field(default="default", max_length=100)
    key_prefix: str = Field(max_length=30)
    # 内网管理端需要按 Agent 自动回填调试凭证，因此保留完整明文；
    # repr=False 避免 ORM 对象被调试打印时直接暴露完整 Key。
    api_key: str = Field(max_length=255, repr=False)
    key_hash: str = Field(max_length=64, unique=True)
    status: str = Field(default="enabled", max_length=30)
    expires_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=now_time)
    updated_at: datetime = Field(default_factory=now_time)


class BusinessPlatformAgent(SQLModel, table=True):
    """业务平台与 Agent 模板的多对多关联模型。"""

    __tablename__ = "business_platform_agents"
    __table_args__ = {"schema": "platform"}

    platform_id: int = Field(
        sa_column=Column(
            BigInteger,
            ForeignKey("platform.business_platforms.id", ondelete="CASCADE"),
            primary_key=True,
        )
    )
    agent_template_id: int = Field(
        sa_column=Column(
            BigInteger,
            ForeignKey("agent.agent_templates.id", ondelete="CASCADE"),
            primary_key=True,
        )
    )
    created_at: datetime = Field(default_factory=now_time)


class BusinessPlatformMCPTool(SQLModel, table=True):
    """业务平台与 MCP Tool 的多对多关联模型。"""

    __tablename__ = "business_platform_mcp_tools"
    __table_args__ = {"schema": "platform"}

    platform_id: int = Field(
        sa_column=Column(
            BigInteger,
            ForeignKey("platform.business_platforms.id", ondelete="CASCADE"),
            primary_key=True,
        )
    )
    mcp_tool_id: int = Field(
        sa_column=Column(
            BigInteger,
            ForeignKey("mcp.mcp_tools.id", ondelete="CASCADE"),
            primary_key=True,
        )
    )
    created_at: datetime = Field(default_factory=now_time)
