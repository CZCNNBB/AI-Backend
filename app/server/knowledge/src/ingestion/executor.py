"""知识文档入库任务执行器。"""

import hashlib
import time
from datetime import datetime, timezone
from typing import Any

from sqlmodel import select

from app.common.db.postgres_db import get_db_session
from app.server.file.src.service.file_service import FileService
from app.server.knowledge.src.config import knowledge_config
from app.server.agent.src.model.resource import resolve_model_resource
from app.server.knowledge.src.embedding.schemas import PersistentVectorRecord, PersistentVectorWrite
from app.server.knowledge.src.embedding.service import embedding_service
from app.server.knowledge.src.logging_config import logger
from app.server.knowledge.src.models import IngestionRun, KnowledgeBase, KnowledgeChunk, KnowledgeDocument
from app.server.knowledge.src.repositories import KnowledgeChunkRepository
from app.server.knowledge.src.split.schemas import (
    MarkdownDocumentHeaderThenRecursiveStrategyConfig,
    SplitMethodConfig,
)
from app.server.knowledge.src.split.service import split_service
from app.server.knowledge.src.vector_store.milvus_store import vector_store_service


def utc_now() -> datetime:
    """返回带时区的 UTC 时间。"""
    return datetime.now(timezone.utc)


class IngestionExecutor:
    """执行文件读取、切片、向量化、Milvus 写入和分块证据落库。"""

    def __init__(self) -> None:
        """初始化可复用的文件服务和分块 Repository。"""
        self.file_service = FileService()
        self.chunk_repository = KnowledgeChunkRepository()

    async def execute(self, run: IngestionRun) -> None:
        """按照任务类型执行入库、重新索引或文档删除。"""
        if run.operation == "delete":
            await self._execute_delete(run)
            return
        if run.operation not in {"ingest", "reindex"}:
            raise ValueError(f"当前执行器暂不支持任务类型: {run.operation}")

        knowledge, document, file_record = await self._load_sources(run)
        content = await self.file_service.read_record_content(file_record)
        if not content.strip():
            raise ValueError("文件内容源为空，无法执行知识入库")
        logger.info(
            "知识入库内容源读取完成: run_id=%s file_id=%s file_name=%r converter=%s content_chars=%s",
            run.run_id,
            run.file_id,
            file_record.original_name,
            file_record.converter_name or "无需转换",
            len(content),
        )

        # 优先使用任务提交时保存的文档级配置快照，旧任务没有快照时回退知识库默认配置。
        task_split_config = (run.payload or {}).get("split_config")
        if task_split_config is not None and not isinstance(task_split_config, dict):
            raise ValueError("入库任务 split_config 必须是 JSON 对象")
        split_result = self._split_content(
            content,
            task_split_config if task_split_config is not None else knowledge.split_config,
        )
        chunks = split_result["chunks"]
        if not chunks:
            raise ValueError("文件切片结果为空，无法执行知识入库")
        logger.info(
            "知识文档切片完成: run_id=%s split_method=%s split_strategy=%s chunk_count=%s",
            run.run_id,
            split_result["split_method"],
            split_result["split_strategy"] or "无",
            len(chunks),
        )

        target_version = document.index_version + 1 if run.operation == "reindex" else document.index_version
        chunk_records: list[KnowledgeChunk] = []
        try:
            # 每次尝试都先清理该文件旧向量，防止重试时残留重复或脏数据。
            await vector_store_service.delete_file_vectors(knowledge.collection_name, run.file_id)
            logger.info(
                "知识入库旧向量清理完成: run_id=%s collection=%s file_id=%s",
                run.run_id,
                knowledge.collection_name,
                run.file_id,
            )

            # 单次入库只解析一次模型连接信息，并按模型配置的 batch_size 分批处理。
            embedding_resource = resolve_model_resource(knowledge.embedding_model, "embedding")
            batch_size = embedding_resource.embedding_batch_size
            total_batches = (len(chunks) + batch_size - 1) // batch_size
            logger.info(
                "知识入库向量化开始: run_id=%s model_code=%s dimension=%s chunk_count=%s batch_size=%s total_batches=%s",
                run.run_id,
                knowledge.embedding_model,
                knowledge.embedding_dimension,
                len(chunks),
                batch_size,
                total_batches,
            )
            for batch_index, batch_start in enumerate(range(0, len(chunks), batch_size), start=1):
                chunk_batch = chunks[batch_start:batch_start + batch_size]
                batch_started_at = time.perf_counter()
                logger.info(
                    "知识入库批次开始: run_id=%s batch=%s/%s chunks=%s",
                    run.run_id,
                    batch_index,
                    total_batches,
                    len(chunk_batch),
                )
                embeddings = await embedding_service.embed_texts(
                    texts=[chunk.content for chunk in chunk_batch],
                    model_code=knowledge.embedding_model,
                    resource=embedding_resource,
                )
                if len(embeddings) != len(chunk_batch):
                    raise ValueError(
                        "Embedding 批量结果数量与 Chunk 数量不一致: "
                        f"chunks={len(chunk_batch)}, embeddings={len(embeddings)}"
                    )

                vector_writes: list[PersistentVectorWrite] = []
                batch_chunk_records: list[KnowledgeChunk] = []
                for chunk, embedding in zip(chunk_batch, embeddings, strict=True):
                    chunk_id = self._build_chunk_id(
                        knowledge_id=run.knowledge_id,
                        file_id=run.file_id,
                        index_version=target_version,
                        chunk_index=chunk.chunk_index,
                    )
                    vector_record = PersistentVectorRecord(
                        collection_name=knowledge.collection_name,
                        chunk_id=chunk_id,
                        file_id=run.file_id,
                        source=file_record.original_name,
                        chunk_index=chunk.chunk_index,
                        metadata=chunk.metadata,
                    )
                    vector_writes.append(
                        PersistentVectorWrite(
                            text=chunk.content,
                            embedding=embedding,
                            record=vector_record,
                        )
                    )
                    batch_chunk_records.append(
                        KnowledgeChunk(
                            knowledge_id=run.knowledge_id,
                            document_id=int(document.id),
                            file_id=run.file_id,
                            chunk_id=chunk_id,
                            index_version=target_version,
                            chunk_index=chunk.chunk_index,
                            raw_content=chunk.content,
                            content_hash=hashlib.sha256(chunk.content.encode("utf-8")).hexdigest(),
                            char_count=chunk.char_count,
                            context=self._build_context(chunk.metadata),
                            extra_metadata=chunk.metadata,
                            vector_id=chunk_id,
                        )
                    )

                await vector_store_service.insert_many(
                    writes=vector_writes,
                    expected_dimension=knowledge.embedding_dimension,
                )
                chunk_records.extend(batch_chunk_records)
                logger.info(
                    "知识入库批次完成: run_id=%s batch=%s/%s chunks=%s elapsed_seconds=%.3f",
                    run.run_id,
                    batch_index,
                    total_batches,
                    len(chunk_batch),
                    time.perf_counter() - batch_started_at,
                )

            # 整份文档写完后统一刷新，保证数据库提交成功时全部向量均已可检索。
            await vector_store_service.flush_collection(knowledge.collection_name)
            logger.info(
                "知识入库 Milvus 刷新完成: run_id=%s collection=%s vector_count=%s",
                run.run_id,
                knowledge.collection_name,
                len(chunk_records),
            )
        except Exception:
            # 单个分块失败时，前面已经成功写入的向量不能留在可检索 Collection 中。
            await self._cleanup_file_vectors(knowledge.collection_name, run)
            raise

        # Milvus 全部写入成功后再替换 PostgreSQL 证据，避免数据库先显示成功但向量并不完整。
        with get_db_session() as db:
            try:
                current_document = db.get(KnowledgeDocument, document.id)
                if current_document is None:
                    raise ValueError(f"知识库文档关系已被删除: {document.id}")

                # 分块证据和文档索引快照必须在同一 PostgreSQL 事务中提交，
                # 防止只更新其中一部分后形成版本、数量与实际分块不一致。
                self.chunk_repository.replace_document_chunks(db, int(document.id), chunk_records)
                current_document.index_version = target_version
                current_document.chunk_count = len(chunk_records)
                current_document.index_config = {
                    "split": split_result["effective_config"],
                    "split_method": split_result["split_method"],
                    "split_strategy": split_result["split_strategy"],
                    "embedding_model": knowledge.embedding_model,
                    "embedding_dimension": knowledge.embedding_dimension,
                    "embedding_batch_size": embedding_resource.embedding_batch_size,
                }
                current_document.error_message = None
                current_document.updated_at = utc_now()
                db.add(current_document)
                db.commit()
                logger.info(
                    "知识入库 PostgreSQL 证据提交完成: run_id=%s document_id=%s index_version=%s chunk_count=%s",
                    run.run_id,
                    document.id,
                    target_version,
                    len(chunk_records),
                )
            except Exception:
                db.rollback()
                # PostgreSQL 最终提交失败时也必须回收本次 Milvus 写入，
                # 否则任务显示失败但残留向量仍可能被检索到。
                await self._cleanup_file_vectors(knowledge.collection_name, run)
                raise

    async def _execute_delete(self, run: IngestionRun) -> None:
        """幂等删除文档向量和 PostgreSQL 分块证据。"""
        logger.info(
            "知识文档删除执行开始: run_id=%s knowledge_id=%s file_id=%s",
            run.run_id,
            run.knowledge_id,
            run.file_id,
        )
        with get_db_session() as db:
            knowledge = db.exec(
                select(KnowledgeBase).where(KnowledgeBase.knowledge_id == run.knowledge_id)
            ).first()
            document = db.get(KnowledgeDocument, run.document_id)
            if knowledge is None:
                raise ValueError(f"删除任务关联的知识库不存在: {run.knowledge_id}")
            if document is None:
                # 文档关系已被级联删除时，删除目标已经达成。
                return
            collection_name = knowledge.collection_name
            document_id = int(document.id)

        # Milvus 删除和 PostgreSQL 删除无法放在同一事务中。
        # 先幂等删除向量，再删除证据；任一步失败都可由同一个任务安全重试。
        await vector_store_service.delete_file_vectors_if_exists(
            collection_name=collection_name,
            file_id=run.file_id,
        )
        logger.info(
            "知识文档 Milvus 向量删除完成: run_id=%s collection=%s file_id=%s",
            run.run_id,
            collection_name,
            run.file_id,
        )

        with get_db_session() as db:
            current_document = db.get(KnowledgeDocument, document_id)
            if current_document is None:
                return
            self.chunk_repository.delete_document_chunks(db, document_id)
            current_document.chunk_count = 0
            current_document.index_config = {}
            current_document.indexed_at = None
            current_document.error_message = None
            current_document.updated_at = utc_now()
            db.add(current_document)
            db.commit()
        logger.info(
            "知识文档 PostgreSQL 证据删除完成: run_id=%s document_id=%s",
            run.run_id,
            document_id,
        )

    @staticmethod
    async def _cleanup_file_vectors(collection_name: str, run: IngestionRun) -> None:
        """尽力清理失败任务产生的文件向量，同时保留原始异常供队列处理。"""
        try:
            await vector_store_service.delete_file_vectors(collection_name, run.file_id)
        except Exception:
            # 清理失败不能覆盖真正的入库错误，日志保留知识库和文件定位信息。
            logger.exception(
                "知识入库失败后的 Milvus 脏向量清理失败: knowledge_id=%s file_id=%s",
                run.knowledge_id,
                run.file_id,
            )

    async def _load_sources(self, run: IngestionRun) -> tuple[KnowledgeBase, KnowledgeDocument, Any]:
        """读取并校验任务关联的知识库、文档关系和文件内容源。"""
        with get_db_session() as db:
            knowledge = db.exec(
                select(KnowledgeBase).where(KnowledgeBase.knowledge_id == run.knowledge_id)
            ).first()
            document = db.get(KnowledgeDocument, run.document_id)
            if knowledge is None or knowledge.status != "active":
                raise ValueError(f"任务关联的可用知识库不存在: {run.knowledge_id}")
            if document is None:
                raise ValueError(f"任务关联的知识库文档不存在: {run.document_id}")

            # 先结束知识库元数据读取 Session。MinerU 轮询期间不能持有这条数据库连接。
            db.expunge(knowledge)
            db.expunge(document)

        # 文件服务使用“标记 processing → 关闭 Session → 解析 → 短事务落结果”的流程，
        # 知识库只消费最终内容源，不重复实现 PDF、MinerU 或 Markdown 解析协议。
        file_record = await self.file_service.prepare_content_source(run.file_id)
        if not self.file_service.is_content_source_ready(file_record):
            raise ValueError(self.file_service.get_content_not_ready_message(file_record))
        return knowledge, document, file_record

    def _split_content(self, content: str, raw_config: dict[str, Any]) -> dict[str, Any]:
        """根据知识库保存的配置选择单一切片方式或组合切片策略。"""
        config = dict(raw_config or {})
        split_type = str(config.get("type") or knowledge_config.split_default_method)
        if split_type == "markdown_document_header_then_recursive":
            strategy = MarkdownDocumentHeaderThenRecursiveStrategyConfig.model_validate(config)
            method = SplitMethodConfig(
                type=knowledge_config.split_default_method,
                chunk_size=knowledge_config.split_chunk_size,
                chunk_overlap=knowledge_config.split_chunk_overlap,
            )
            return split_service.split(text=content, method=method, strategy=strategy)

        method = SplitMethodConfig.model_validate(
            {
                "type": split_type,
                "chunk_size": config.get("chunk_size", knowledge_config.split_chunk_size),
                "chunk_overlap": config.get("chunk_overlap", knowledge_config.split_chunk_overlap),
                "separator": config.get("separator", "\n\n\n"),
                "headers": config.get("headers", ["#", "##", "###", "####"]),
            }
        )
        return split_service.split(text=content, method=method)

    @staticmethod
    def _build_chunk_id(
        *,
        knowledge_id: str,
        file_id: str,
        index_version: int,
        chunk_index: int,
    ) -> str:
        """生成不超过 Milvus 长度限制、可稳定重算的分块 ID。"""
        seed = f"{knowledge_id}:{file_id}:{index_version}:{chunk_index}"
        return f"chunk_{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:40]}"

    @staticmethod
    def _build_context(metadata: dict[str, Any]) -> str | None:
        """把结构化标题层级转换为便于引用展示的上下文文本。"""
        headers = metadata.get("headers")
        if not isinstance(headers, dict):
            return None
        values = [str(value).strip() for value in headers.values() if str(value).strip()]
        return " > ".join(values) or None


ingestion_executor = IngestionExecutor()
