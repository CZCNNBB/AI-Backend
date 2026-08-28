from datetime import datetime

from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


def now_time() -> datetime:
    """返回当前时间，用于文件记录默认时间字段。"""
    return datetime.now()


class UploadedFileRecord(SQLModel, table=True):
    """上传文件记录表模型，对应 agent.uploaded_files。"""

    __tablename__ = "uploaded_files"
    __table_args__ = {"schema": "agent"}

    file_id: str = Field(max_length=100, primary_key=True)
    original_name: str = Field(max_length=500)
    stored_name: str = Field(max_length=255)
    storage_path: str

    extension: str = Field(default="", max_length=50)
    mime_type: str | None = Field(default=None, max_length=255)
    size_bytes: int = Field(default=0)
    # 长期文件由知识库等持久业务使用；临时文件允许后台按保留时长自动清理。
    is_long_term: bool = Field(default=False)

    status: str = Field(default="uploaded", max_length=30)
    content_path: str | None = Field(default=None)
    content_type: str = Field(default="pending", max_length=30)
    conversion_status: str = Field(default="pending", max_length=30)
    conversion_error: str | None = Field(default=None)
    converter_name: str | None = Field(default=None, max_length=100)
    converted_at: datetime | None = Field(default=None)

    extra_metadata: dict | None = Field(default=None, sa_column=Column("metadata", JSONB, nullable=True))

    created_at: datetime = Field(default_factory=now_time)
    updated_at: datetime = Field(default_factory=now_time)
