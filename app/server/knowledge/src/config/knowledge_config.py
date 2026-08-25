"""知识库服务统一配置。"""

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class KnowledgeConfig(BaseSettings):
    """统一管理切片、向量化、向量库和检索配置。"""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    split_default_method: str = Field(default="recursive_character")
    split_chunk_size: int = Field(default=1000, ge=1)
    split_chunk_overlap: int = Field(default=200, ge=0)

    http_max_keepalive_connections: int = Field(default=5, ge=1)
    http_max_connections: int = Field(default=10, ge=1)

    milvus_uri: str = Field(default="http://127.0.0.1:19530")
    milvus_token: str = Field(default="")
    milvus_database: str = Field(default="career_ai")
    milvus_connect_timeout: float = Field(default=8, ge=1)
    milvus_write_timeout: float = Field(default=15, ge=1)
    milvus_query_timeout: float = Field(default=15, ge=1)
    milvus_nprobe: int = Field(default=10, ge=1)

    metadata_headers_weight: float = Field(default=0.6, ge=0, le=10, alias="RETRIEVAL_METADATA_HEADERS_WEIGHT")
    document_max_chunks: int = Field(default=5000, ge=1, alias="RETRIEVAL_DOCUMENT_MAX_CHUNKS")

    startup_health_check_timeout: float = Field(default=15, ge=1, alias="KNOWLEDGE_STARTUP_HEALTH_CHECK_TIMEOUT")

    ingestion_worker_count: int = Field(default=1, ge=1, le=16, alias="KNOWLEDGE_INGESTION_WORKER_COUNT")
    ingestion_poll_interval_seconds: float = Field(
        default=1,
        ge=0.1,
        alias="KNOWLEDGE_INGESTION_POLL_INTERVAL_SECONDS",
    )
    ingestion_heartbeat_seconds: int = Field(default=10, ge=1, alias="KNOWLEDGE_INGESTION_HEARTBEAT_SECONDS")
    ingestion_stale_seconds: int = Field(default=60, ge=5, alias="KNOWLEDGE_INGESTION_STALE_SECONDS")
    ingestion_recovery_interval_seconds: int = Field(
        default=30,
        ge=5,
        alias="KNOWLEDGE_INGESTION_RECOVERY_INTERVAL_SECONDS",
    )
    ingestion_max_retries: int = Field(default=3, ge=0, alias="KNOWLEDGE_INGESTION_MAX_RETRIES")
    ingestion_retry_delay_seconds: int = Field(default=5, ge=1, alias="KNOWLEDGE_INGESTION_RETRY_DELAY_SECONDS")

    @model_validator(mode="after")
    def validate_split_config(self) -> "KnowledgeConfig":
        """校验默认切片长度与重叠长度之间的关系。"""
        if self.split_chunk_overlap >= self.split_chunk_size:
            raise ValueError("SPLIT_CHUNK_OVERLAP 必须小于 SPLIT_CHUNK_SIZE")
        if self.ingestion_stale_seconds <= self.ingestion_heartbeat_seconds * 2:
            raise ValueError("KNOWLEDGE_INGESTION_STALE_SECONDS 必须大于心跳间隔的两倍")
        return self


knowledge_config = KnowledgeConfig()

