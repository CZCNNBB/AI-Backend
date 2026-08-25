from datetime import datetime
from typing import Any

from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


def now_time() -> datetime:
    """返回当前时间，用作模型配置记录的默认时间字段。"""
    return datetime.now()


class ModelConfigRecord(SQLModel, table=True):
    """平台模型配置表模型，对应 public.model_configs。"""

    __tablename__ = "model_configs"

    id: int | None = Field(default=None, primary_key=True)

    model_code: str = Field(max_length=100, unique=True)
    model_name: str = Field(max_length=255)
    model_type: str = Field(max_length=50)

    base_url: str
    api_key: str | None = Field(default=None)
    api_type: str = Field(default="openai_compatible", max_length=50)

    support_stream: bool = Field(default=False)
    support_tool_calling: bool = Field(default=False)
    support_structured_output: bool = Field(default=False)
    is_multimodal: bool = Field(default=False)

    enabled: bool = Field(default=True)

    extra_config: dict[str, Any] | None = Field(default=None, sa_column=Column(JSONB, nullable=True))
    description: str | None = Field(default=None)

    created_at: datetime = Field(default_factory=now_time)
    updated_at: datetime = Field(default_factory=now_time)
