"""知识库定义、文档生命周期和入库任务提交业务服务。"""

import re
from typing import Any
from uuid import uuid4

from sqlmodel import Session, select

from app.server.agent.src.model.service import ModelConfigService
from app.server.file.src.models.file_models import UploadedFileRecord
from app.server.knowledge.src.config import knowledge_config
from app.server.knowledge.src.ingestion.queue_service import ingestion_queue_service
from app.server.knowledge.src.logging_config import logger
from app.server.knowledge.src.models import KnowledgeBase, KnowledgeDocument
from app.server.knowledge.src.repositories import (
    KnowledgeBaseRepository,
    KnowledgeChunkRepository,
    KnowledgeDocumentRepository,
)
from app.server.knowledge.src.schemas.knowledge_schemas import (
    IngestionRunResponse,
    KnowledgeBaseCreateRequest,
    KnowledgeBaseResponse,
    KnowledgeBaseSearchRequest,
    KnowledgeBaseUpdateRequest,
    KnowledgeDocumentDeleteResponse,
    KnowledgeDocumentReindexRequest,
    KnowledgeDocumentResponse,
    KnowledgeDocumentSearchRequest,
    KnowledgeDocumentSubmitRequest,
    KnowledgeDocumentSubmitResponse,
)
from app.server.knowledge.src.split.schemas import (
    MarkdownDocumentHeaderThenRecursiveStrategyConfig,
    SplitMethodConfig,
)
from app.server.knowledge.src.vector_store.milvus_store import vector_store_service


class KnowledgeManagementService:
    """管理知识库、文档生命周期和异步索引任务提交。"""

    def __init__(self) -> None:
        """初始化知识库相关 Repository 和模型配置服务。"""
        self.knowledge_repository = KnowledgeBaseRepository()
        self.document_repository = KnowledgeDocumentRepository()
        self.chunk_repository = KnowledgeChunkRepository()
        self.model_config_service = ModelConfigService()

    async def create_knowledge_base(
        self, db: Session, request: KnowledgeBaseCreateRequest
    ) -> KnowledgeBaseResponse:
        """创建 PostgreSQL 知识库记录及对应 Milvus Collection。"""
        knowledge_id = f"kb_{uuid4().hex}"
        collection_name = self._build_collection_name(knowledge_id)
        split_config = self._normalize_split_config(request.split_config)
        model = self.model_config_service.require_enabled_model(
            db, request.embedding_model_code, "embedding"
        )
        dimension = (model.extra_config or {}).get("dimension")
        if not isinstance(dimension, int) or dimension <= 0:
            raise ValueError(f"Embedding 模型 {model.model_code} 必须配置 extra_config.dimension")
        await vector_store_service.create_collection(
            collection_name=collection_name,
            model_name=model.model_code,
            dimension=dimension,
        )
        record = KnowledgeBase(
            knowledge_id=knowledge_id,
            name=request.name.strip(),
            description=request.description,
            collection_name=collection_name,
            embedding_model=model.model_code,
            embedding_dimension=dimension,
            split_config=split_config,
            extra_metadata=request.metadata,
        )
        try:
            saved = self.knowledge_repository.add(db, record)
            # Collection 已经创建，必须在 Service 边界显式提交数据库记录，
            # 这样提交失败时才能在当前方法内删除外部 Collection 进行补偿。
            db.commit()
            db.refresh(saved)
        except Exception:
            db.rollback()
            # PostgreSQL 写入失败时回收刚创建的 Collection，避免留下孤儿资源。
            await vector_store_service.drop_collection(collection_name)
            raise
        return self.to_knowledge_response(saved)

    def get_knowledge_base(self, db: Session, knowledge_id: str) -> KnowledgeBaseResponse:
        """根据知识库 ID 查询详情。"""
        return self.to_knowledge_response(self._require_knowledge(db, knowledge_id))

    def search_knowledge_bases(
        self, db: Session, request: KnowledgeBaseSearchRequest
    ) -> list[KnowledgeBaseResponse]:
        """按照名称关键字和状态查询知识库列表。"""
        records = self.knowledge_repository.search(db, request.keyword, request.status)
        return [self.to_knowledge_response(record) for record in records]

    def update_knowledge_base(
        self, db: Session, request: KnowledgeBaseUpdateRequest
    ) -> KnowledgeBaseResponse:
        """修改知识库基础信息、状态和后续文档默认切片配置。"""
        record = self._require_knowledge(db, request.knowledge_id)
        if record.status == "deleted":
            raise ValueError("已删除的知识库不能修改")
        fields = request.model_fields_set
        if "name" in fields and request.name is not None:
            record.name = request.name.strip()
        if "description" in fields:
            record.description = request.description
        if "split_config" in fields:
            # 显式传 null 表示恢复系统默认切片配置。
            record.split_config = self._normalize_split_config(request.split_config or {})
        if "status" in fields and request.status is not None:
            record.status = request.status
        if "metadata" in fields:
            # metadata 在数据库中非空，显式传 null 时按清空处理。
            record.extra_metadata = request.metadata or {}
        return self.to_knowledge_response(self.knowledge_repository.update(db, record))

    async def delete_knowledge_base(
        self, db: Session, knowledge_id: str
    ) -> KnowledgeBaseResponse:
        """删除 Milvus Collection，并软删除知识库及其全部文档关系。"""
        record = self._require_knowledge(db, knowledge_id)
        if record.status == "deleted":
            return self.to_knowledge_response(record)
        if ingestion_queue_service.has_active_for_knowledge(db, knowledge_id):
            raise ValueError("知识库仍有待执行或运行中的任务，请先等待任务完成或取消待执行任务")

        # 先禁用检索入口；外部资源清理失败时也不会继续参与业务调用。
        record.status = "disabled"
        self.knowledge_repository.update(db, record)
        # 禁用状态必须先独立提交，再执行可能较慢的 Milvus 网络调用。
        # 这既保证其他请求立即停止检索，也避免跨外部调用长期持有数据库事务。
        db.commit()
        await vector_store_service.drop_collection(record.collection_name)
        try:
            self.chunk_repository.delete_knowledge_chunks(db, knowledge_id)
            documents = db.exec(
                select(KnowledgeDocument).where(
                    KnowledgeDocument.knowledge_id == knowledge_id
                )
            ).all()
            for document in documents:
                document.status = "deleted"
                document.chunk_count = 0
                document.indexed_at = None
                document.error_message = None
                db.add(document)
            record.status = "deleted"
            db.add(record)
            db.commit()
            db.refresh(record)
        except Exception:
            db.rollback()
            raise
        return self.to_knowledge_response(record)

    def search_documents(
        self, db: Session, request: KnowledgeDocumentSearchRequest
    ) -> list[KnowledgeDocumentResponse]:
        """查询知识库下的文档及上传文件基础信息。"""
        self._require_knowledge(db, request.knowledge_id)
        records = self.document_repository.search(
            db,
            knowledge_id=request.knowledge_id,
            status=request.status,
            file_name=request.file_name,
        )
        return [
            self.to_document_response(document, uploaded_file)
            for document, uploaded_file in records
        ]

    def get_document(
        self, db: Session, knowledge_id: str, file_id: str
    ) -> KnowledgeDocumentResponse:
        """查询单个知识库文档详情。"""
        document = self._require_document(db, knowledge_id, file_id)
        return self.to_document_response(document, self._get_uploaded_file(db, file_id))

    def submit_document(
        self, db: Session, request: KnowledgeDocumentSubmitRequest
    ) -> KnowledgeDocumentSubmitResponse:
        """建立知识库文件关系，并提交 ingest 或 reindex 任务。"""
        knowledge = self._require_active_knowledge(db, request.knowledge_id)
        uploaded_file = self._require_indexable_uploaded_file(db, request.file_id)
        if uploaded_file.conversion_status == "failed":
            raise ValueError(
                f"上传文件内容源构建失败: {uploaded_file.conversion_error or '未知原因'}"
            )
        document = self.document_repository.get_by_knowledge_and_file(
            db, request.knowledge_id, request.file_id
        )
        if document is None:
            document = self.document_repository.add(
                db,
                KnowledgeDocument(
                    knowledge_id=request.knowledge_id,
                    file_id=request.file_id,
                ),
            )
        elif document.status == "indexed" and not request.force_reindex:
            logger.info(
                "知识文档已完成索引，跳过重复提交: knowledge_id=%s file_id=%s document_id=%s",
                request.knowledge_id,
                request.file_id,
                document.id,
            )
            return KnowledgeDocumentSubmitResponse(
                document=self.to_document_response(document, uploaded_file),
                run=None,
                reused_active_run=False,
            )

        operation = "reindex" if request.force_reindex else "ingest"
        split_config = self._resolve_document_split_config(request, knowledge.split_config)
        run, reused = ingestion_queue_service.submit(
            db,
            document=document,
            operation=operation,
            priority=request.priority,
            max_retries=knowledge_config.ingestion_max_retries,
            payload={"split_config": split_config},
        )
        if reused:
            if run.operation != operation:
                raise ValueError(
                    f"该文档已有 {run.operation} 任务正在执行，不能同时提交 {operation} 任务"
                )
            active_config = (run.payload or {}).get("split_config") or knowledge.split_config
            if active_config != split_config:
                raise ValueError("该文档已有使用不同切片配置的任务正在执行，请等待任务结束后重试")
        logger.info(
            "知识入库任务提交完成: run_id=%s knowledge_id=%s file_id=%s operation=%s reused=%s priority=%s",
            run.run_id,
            request.knowledge_id,
            request.file_id,
            operation,
            reused,
            request.priority,
        )
        db.refresh(document)
        return KnowledgeDocumentSubmitResponse(
            document=self.to_document_response(document, uploaded_file),
            run=IngestionRunResponse.model_validate(run, from_attributes=True),
            reused_active_run=reused,
        )

    def reindex_document(
        self, db: Session, request: KnowledgeDocumentReindexRequest
    ) -> KnowledgeDocumentSubmitResponse:
        """使用可选的新切片配置提交文档重建索引任务。"""
        self._require_document(db, request.knowledge_id, request.file_id)
        return self.submit_document(
            db,
            KnowledgeDocumentSubmitRequest(
                knowledge_id=request.knowledge_id,
                file_id=request.file_id,
                force_reindex=True,
                priority=request.priority,
                split_method=request.split_method,
                split_strategy=request.split_strategy,
            ),
        )

    def delete_document(
        self, db: Session, knowledge_id: str, file_id: str, priority: int
    ) -> KnowledgeDocumentDeleteResponse:
        """提交异步删除任务，由 Worker 清理 Milvus 和 PostgreSQL 分块。"""
        self._require_active_knowledge(db, knowledge_id)
        document = self._require_document(db, knowledge_id, file_id)
        uploaded_file = self._get_uploaded_file(db, file_id)
        if document.status == "deleted":
            logger.info(
                "知识文档已删除，跳过重复删除: knowledge_id=%s file_id=%s document_id=%s",
                knowledge_id,
                file_id,
                document.id,
            )
            return KnowledgeDocumentDeleteResponse(
                document=self.to_document_response(document, uploaded_file),
                run=None,
                reused_active_run=False,
            )
        run, reused = ingestion_queue_service.submit(
            db,
            document=document,
            operation="delete",
            priority=priority,
            max_retries=knowledge_config.ingestion_max_retries,
            payload={},
        )
        if reused and run.operation != "delete":
            raise ValueError(
                f"该文档已有 {run.operation} 任务正在执行，不能同时提交 delete 任务"
            )
        logger.info(
            "知识删除任务提交完成: run_id=%s knowledge_id=%s file_id=%s reused=%s priority=%s",
            run.run_id,
            knowledge_id,
            file_id,
            reused,
            priority,
        )
        db.refresh(document)
        return KnowledgeDocumentDeleteResponse(
            document=self.to_document_response(document, uploaded_file),
            run=IngestionRunResponse.model_validate(run, from_attributes=True),
            reused_active_run=reused,
        )

    @staticmethod
    def _resolve_document_split_config(
        request: KnowledgeDocumentSubmitRequest,
        knowledge_default: dict[str, Any],
    ) -> dict[str, Any]:
        """解析文档级切片配置；未覆盖时返回知识库默认配置快照。"""
        if request.split_strategy is not None:
            return request.split_strategy.model_dump()
        if request.split_method is not None:
            return request.split_method.model_dump()
        return dict(knowledge_default)

    @staticmethod
    def _normalize_split_config(raw_config: dict[str, Any]) -> dict[str, Any]:
        """校验并补全知识库切片配置，避免无效配置进入数据库。"""
        config = raw_config or {
            "type": knowledge_config.split_default_method,
            "chunk_size": knowledge_config.split_chunk_size,
            "chunk_overlap": knowledge_config.split_chunk_overlap,
        }
        if config.get("type") == "markdown_document_header_then_recursive":
            return MarkdownDocumentHeaderThenRecursiveStrategyConfig.model_validate(
                config
            ).model_dump()
        return SplitMethodConfig.model_validate(config).model_dump()

    def _require_knowledge(self, db: Session, knowledge_id: str) -> KnowledgeBase:
        """读取知识库，不存在时抛出统一业务错误。"""
        record = self.knowledge_repository.get_by_knowledge_id(db, knowledge_id)
        if record is None:
            raise ValueError(f"知识库不存在: {knowledge_id}")
        return record

    def _require_active_knowledge(self, db: Session, knowledge_id: str) -> KnowledgeBase:
        """读取可用知识库，禁用或删除状态不能提交新任务。"""
        record = self._require_knowledge(db, knowledge_id)
        if record.status != "active":
            raise ValueError(f"知识库当前不可用: {knowledge_id}, status={record.status}")
        return record

    def _require_document(
        self, db: Session, knowledge_id: str, file_id: str
    ) -> KnowledgeDocument:
        """读取知识库文档关系，不存在时抛出统一业务错误。"""
        document = self.document_repository.get_by_knowledge_and_file(
            db, knowledge_id, file_id
        )
        if document is None:
            raise ValueError(
                f"知识库文档不存在: knowledge_id={knowledge_id}, file_id={file_id}"
            )
        return document

    @staticmethod
    def _get_uploaded_file(db: Session, file_id: str) -> UploadedFileRecord:
        """读取上传文件元数据；软删除文件仍允许清理其知识库索引。"""
        uploaded_file = db.get(UploadedFileRecord, file_id)
        if uploaded_file is None:
            raise ValueError(f"上传文件记录不存在: {file_id}")
        return uploaded_file

    @classmethod
    def _require_indexable_uploaded_file(
        cls,
        db: Session,
        file_id: str,
    ) -> UploadedFileRecord:
        """读取可入库文件，已删除的源文件不能创建或重建索引。"""
        uploaded_file = cls._get_uploaded_file(db, file_id)
        if uploaded_file.status == "deleted":
            raise ValueError(f"上传文件已删除，不能执行知识入库: {file_id}")
        return uploaded_file

    @staticmethod
    def _build_collection_name(knowledge_id: str) -> str:
        """把知识库 ID 转换为合法且稳定的 Milvus Collection 名称。"""
        normalized = re.sub(r"[^0-9A-Za-z_]", "_", knowledge_id)
        return f"knowledge_{normalized}"[:255]

    @staticmethod
    def to_knowledge_response(record: KnowledgeBase) -> KnowledgeBaseResponse:
        """把知识库数据库模型转换为接口响应。"""
        return KnowledgeBaseResponse(
            knowledge_id=record.knowledge_id,
            name=record.name,
            description=record.description,
            collection_name=record.collection_name,
            embedding_model_code=record.embedding_model,
            embedding_dimension=record.embedding_dimension,
            split_config=record.split_config,
            status=record.status,
            metadata=record.extra_metadata,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    @staticmethod
    def to_document_response(
        record: KnowledgeDocument,
        uploaded_file: UploadedFileRecord | None = None,
    ) -> KnowledgeDocumentResponse:
        """把文档关系和上传文件信息合并为接口响应。"""
        return KnowledgeDocumentResponse(
            id=int(record.id),
            knowledge_id=record.knowledge_id,
            file_id=record.file_id,
            file_name=uploaded_file.original_name if uploaded_file else None,
            mime_type=uploaded_file.mime_type if uploaded_file else None,
            size_bytes=uploaded_file.size_bytes if uploaded_file else None,
            status=record.status,
            index_version=record.index_version,
            chunk_count=record.chunk_count,
            error_message=record.error_message,
            indexed_at=record.indexed_at,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )


knowledge_management_service = KnowledgeManagementService()
