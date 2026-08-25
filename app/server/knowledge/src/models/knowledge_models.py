"""知识库 PostgreSQL 数据模型。"""

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Column, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


def utc_now() -> datetime:
    """返回带时区的 UTC 时间，供知识库模型默认时间字段使用。"""
    return datetime.now(timezone.utc)


class KnowledgeBase(SQLModel, table=True):
    """知识库定义与默认索引配置，对应 knowledge.knowledge_bases。"""

    __tablename__ = "knowledge_bases"
    __table_args__ = {"schema": "knowledge"}

    id: int | None = Field(default=None, primary_key=True)
    knowledge_id: str = Field(max_length=100, unique=True, index=True)
    name: str = Field(max_length=255)
    description: str | None = Field(default=None)
    collection_name: str = Field(max_length=255, unique=True)
    embedding_model: str = Field(max_length=255)
    embedding_dimension: int = Field(gt=0)
    split_config: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False),
    )
    status: str = Field(default="active", max_length=30)
    extra_metadata: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column("metadata", JSONB, nullable=False),
    )
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class KnowledgeDocument(SQLModel, table=True):
    """知识库与上传文件的关联及索引状态，对应 knowledge.knowledge_documents。"""

    __tablename__ = "knowledge_documents"
    __table_args__ = (
        UniqueConstraint("knowledge_id", "file_id", name="uq_knowledge_documents_kb_file"),
        {"schema": "knowledge"},
    )

    id: int | None = Field(default=None, primary_key=True)
    knowledge_id: str = Field(
        max_length=100,
        foreign_key="knowledge.knowledge_bases.knowledge_id",
        index=True,
    )
    # Agent 与 Knowledge 位于同一个 career_ai 数据库，通过 Schema 隔离并建立真实外键。
    file_id: str = Field(max_length=100, foreign_key="agent.uploaded_files.file_id", index=True)
    status: str = Field(default="pending", max_length=30, index=True)
    index_version: int = Field(default=1, gt=0)
    chunk_count: int = Field(default=0, ge=0)
    index_config: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False),
    )
    error_message: str | None = Field(default=None)
    indexed_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class IngestionRun(SQLModel, table=True):
    """知识入库排队任务和运行记录，对应 knowledge.ingestion_runs。"""

    __tablename__ = "ingestion_runs"
    __table_args__ = {"schema": "knowledge"}

    run_id: str = Field(max_length=100, primary_key=True)
    document_id: int = Field(foreign_key="knowledge.knowledge_documents.id", index=True)
    knowledge_id: str = Field(max_length=100, index=True)
    file_id: str = Field(max_length=100, index=True)
    operation: str = Field(default="ingest", max_length=30)
    status: str = Field(default="pending", max_length=30, index=True)
    priority: int = Field(default=0)
    payload: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False),
    )
    worker_id: str | None = Field(default=None, max_length=150, index=True)
    heartbeat_at: datetime | None = Field(default=None)
    retry_count: int = Field(default=0, ge=0)
    max_retries: int = Field(default=3, ge=0)
    available_at: datetime = Field(default_factory=utc_now)
    error_message: str | None = Field(default=None)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    started_at: datetime | None = Field(default=None)
    completed_at: datetime | None = Field(default=None)


class KnowledgeChunk(SQLModel, table=True):
    """知识分块证据及向量映射，对应 knowledge.knowledge_chunks。"""

    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        UniqueConstraint("knowledge_id", "chunk_id", name="uq_knowledge_chunks_kb_chunk"),
        UniqueConstraint(
            "document_id",
            "index_version",
            "chunk_index",
            name="uq_knowledge_chunks_document_version_index",
        ),
        {"schema": "knowledge"},
    )

    id: int | None = Field(default=None, primary_key=True)
    knowledge_id: str = Field(max_length=100, index=True)
    document_id: int = Field(foreign_key="knowledge.knowledge_documents.id", index=True)
    file_id: str = Field(max_length=100, index=True)
    chunk_id: str = Field(max_length=100, index=True)
    index_version: int = Field(gt=0)
    chunk_index: int = Field(ge=0)
    raw_content: str
    content_hash: str = Field(max_length=64)
    char_count: int = Field(ge=0)
    context: str | None = Field(default=None)
    extra_metadata: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column("metadata", JSONB, nullable=False),
    )
    vector_id: str = Field(max_length=100)
    created_at: datetime = Field(default_factory=utc_now)
