"""知识库、文档关系和分块数据访问层。"""

from datetime import datetime, timezone

from sqlmodel import Session, col, delete, select

from app.server.file.src.models.file_models import UploadedFileRecord
from app.server.knowledge.src.models import KnowledgeBase, KnowledgeChunk, KnowledgeDocument


def utc_now() -> datetime:
    """返回带时区 UTC 时间，统一更新持久化记录时间。"""
    return datetime.now(timezone.utc)


class KnowledgeBaseRepository:
    """知识库定义数据访问层。"""

    def add(self, db: Session, record: KnowledgeBase) -> KnowledgeBase:
        """新增知识库记录。"""
        db.add(record)
        db.commit()
        db.refresh(record)
        return record

    def update(self, db: Session, record: KnowledgeBase) -> KnowledgeBase:
        """保存知识库基础信息或生命周期状态变化。"""
        record.updated_at = utc_now()
        db.add(record)
        db.commit()
        db.refresh(record)
        return record

    def get_by_knowledge_id(self, db: Session, knowledge_id: str) -> KnowledgeBase | None:
        """根据对外知识库 ID 查询知识库。"""
        statement = select(KnowledgeBase).where(KnowledgeBase.knowledge_id == knowledge_id)
        return db.exec(statement).first()

    def get_by_collection_names(
        self,
        db: Session,
        collection_names: list[str],
    ) -> list[KnowledgeBase]:
        """按 Collection 名称批量查询知识库，供检索阶段解析绑定模型。"""
        # 禁用或已删除知识库不能继续参与检索和模型配置解析。
        statement = select(KnowledgeBase).where(
            col(KnowledgeBase.collection_name).in_(collection_names),
            KnowledgeBase.status == "active",
        )
        return list(db.exec(statement).all())

    def search(self, db: Session, keyword: str | None, status: str | None) -> list[KnowledgeBase]:
        """按名称关键字和状态查询知识库列表。"""
        statement = select(KnowledgeBase)
        if keyword:
            statement = statement.where(KnowledgeBase.name.ilike(f"%{keyword.strip()}%"))
        if status:
            statement = statement.where(KnowledgeBase.status == status)
        statement = statement.order_by(KnowledgeBase.created_at.desc())
        return list(db.exec(statement).all())


class KnowledgeDocumentRepository:
    """知识库文件关系和索引状态数据访问层。"""

    def add(self, db: Session, record: KnowledgeDocument) -> KnowledgeDocument:
        """新增知识库文件关系。"""
        db.add(record)
        db.commit()
        db.refresh(record)
        return record

    def get_by_id(self, db: Session, document_id: int) -> KnowledgeDocument | None:
        """根据内部文档关系 ID 查询记录。"""
        return db.get(KnowledgeDocument, document_id)

    def get_by_knowledge_and_file(
        self,
        db: Session,
        knowledge_id: str,
        file_id: str,
    ) -> KnowledgeDocument | None:
        """根据知识库 ID 和文件 ID 查询唯一关系。"""
        statement = select(KnowledgeDocument).where(
            KnowledgeDocument.knowledge_id == knowledge_id,
            KnowledgeDocument.file_id == file_id,
        )
        return db.exec(statement).first()

    def search(
        self,
        db: Session,
        *,
        knowledge_id: str,
        status: str | None,
        file_name: str | None,
    ) -> list[tuple[KnowledgeDocument, UploadedFileRecord]]:
        """查询知识库文档并关联文件名称、类型和大小。"""
        statement = (
            select(KnowledgeDocument, UploadedFileRecord)
            .join(UploadedFileRecord, KnowledgeDocument.file_id == UploadedFileRecord.file_id)
            .where(KnowledgeDocument.knowledge_id == knowledge_id)
        )
        if status:
            statement = statement.where(KnowledgeDocument.status == status)
        if file_name and file_name.strip():
            statement = statement.where(
                UploadedFileRecord.original_name.ilike(f"%{file_name.strip()}%")
            )
        statement = statement.order_by(KnowledgeDocument.created_at.desc())
        return list(db.exec(statement).all())

    def update(self, db: Session, record: KnowledgeDocument) -> KnowledgeDocument:
        """保存文档索引状态变化。"""
        record.updated_at = utc_now()
        db.add(record)
        db.commit()
        db.refresh(record)
        return record


class KnowledgeChunkRepository:
    """知识分块证据数据访问层。"""

    def replace_document_chunks(
        self,
        db: Session,
        document_id: int,
        chunks: list[KnowledgeChunk],
    ) -> None:
        """在当前事务中删除文档旧分块并暂存新分块，提交由业务层统一控制。"""
        db.exec(delete(KnowledgeChunk).where(KnowledgeChunk.document_id == document_id))
        db.add_all(chunks)
        # 这里只刷新 SQL，不提交事务；调用方还需要同步更新文档版本和分块数量。
        db.flush()

    def delete_document_chunks(self, db: Session, document_id: int) -> None:
        """在当前事务中删除指定文档的全部 PostgreSQL 分块证据。"""
        db.exec(delete(KnowledgeChunk).where(KnowledgeChunk.document_id == document_id))
        db.flush()

    def delete_knowledge_chunks(self, db: Session, knowledge_id: str) -> None:
        """在当前事务中删除整个知识库的 PostgreSQL 分块证据。"""
        db.exec(delete(KnowledgeChunk).where(KnowledgeChunk.knowledge_id == knowledge_id))
        db.flush()
