"""知识库 PostgreSQL 数据访问层。"""

from app.server.knowledge.src.repositories.knowledge_repository import (
    KnowledgeBaseRepository,
    KnowledgeChunkRepository,
    KnowledgeDocumentRepository,
)

__all__ = ["KnowledgeBaseRepository", "KnowledgeChunkRepository", "KnowledgeDocumentRepository"]
