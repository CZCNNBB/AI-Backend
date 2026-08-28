"""基于 PostgreSQL 的知识入库任务队列。"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, func, select

from app.common.db.postgres_db import get_db_session
from app.server.knowledge.src.logging_config import logger
from app.server.knowledge.src.models import IngestionRun, KnowledgeDocument


def utc_now() -> datetime:
    """返回带时区的 UTC 时间。"""
    return datetime.now(timezone.utc)


class IngestionQueueService:
    """负责入库任务提交、抢占、心跳、重试和僵尸任务恢复。"""

    ACTIVE_STATUSES = ("pending", "running")

    def check_schema(self) -> None:
        """检查四张知识库表是否存在，Worker 启动前缺表时立即失败。"""
        required_tables = (
            "knowledge.knowledge_bases",
            "knowledge.knowledge_documents",
            "knowledge.ingestion_runs",
            "knowledge.knowledge_chunks",
        )
        with get_db_session() as db:
            for table_name in required_tables:
                exists = db.execute(
                    text("SELECT to_regclass(:table_name)"),
                    {"table_name": table_name},
                ).scalar_one()
                if exists is None:
                    raise RuntimeError(
                        f"知识库表不存在: {table_name}，"
                        "请先执行 sql/00000000_init_empty_database.sql"
                    )

    def submit(
        self,
        db: Session,
        *,
        document: KnowledgeDocument,
        operation: str,
        priority: int,
        max_retries: int,
        payload: dict | None = None,
    ) -> tuple[IngestionRun, bool]:
        """提交任务；已有同类型活跃任务时直接复用，保证接口幂等。"""
        active_statement = select(IngestionRun).where(
            IngestionRun.document_id == document.id,
            IngestionRun.status.in_(self.ACTIVE_STATUSES),
        )
        active_run = db.exec(active_statement).first()
        if active_run is not None:
            return active_run, True

        run = IngestionRun(
            run_id=uuid4().hex,
            document_id=int(document.id),
            knowledge_id=document.knowledge_id,
            file_id=document.file_id,
            operation=operation,
            priority=priority,
            max_retries=max_retries,
            payload=payload or {},
        )
        # 删除任务进入独立的 deleting 状态，避免前端把它误认为待入库任务。
        document.status = "deleting" if operation == "delete" else "pending"
        document.error_message = None
        document.updated_at = utc_now()
        db.add(document)
        db.add(run)
        try:
            db.commit()
            db.refresh(run)
            return run, False
        except IntegrityError:
            # 部分唯一索引是并发提交的最终防线；冲突后读取另一请求已创建的活跃任务。
            db.rollback()
            active_run = db.exec(active_statement).first()
            if active_run is None:
                raise
            return active_run, True

    def get(self, db: Session, run_id: str) -> IngestionRun | None:
        """根据任务 ID 查询任务运行记录。"""
        return db.get(IngestionRun, run_id)

    def search(
        self,
        db: Session,
        *,
        knowledge_id: str | None,
        file_id: str | None,
        operation: str | None,
        status: str | None,
        page: int,
        page_size: int,
    ) -> tuple[list[IngestionRun], int]:
        """按筛选条件分页查询任务运行记录。"""
        filters = []
        if knowledge_id:
            filters.append(IngestionRun.knowledge_id == knowledge_id)
        if file_id:
            filters.append(IngestionRun.file_id == file_id)
        if operation:
            filters.append(IngestionRun.operation == operation)
        if status:
            filters.append(IngestionRun.status == status)

        count_statement = select(func.count()).select_from(IngestionRun)
        statement = select(IngestionRun)
        for condition in filters:
            count_statement = count_statement.where(condition)
            statement = statement.where(condition)

        total = int(db.exec(count_statement).one())
        statement = (
            statement
            .order_by(col(IngestionRun.created_at).desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(db.exec(statement).all()), total

    def has_active_for_knowledge(self, db: Session, knowledge_id: str) -> bool:
        """判断知识库是否仍有待执行或运行中的任务。"""
        statement = select(IngestionRun.run_id).where(
            IngestionRun.knowledge_id == knowledge_id,
            col(IngestionRun.status).in_(self.ACTIVE_STATUSES),
        )
        return db.exec(statement).first() is not None

    def cancel_pending(self, db: Session, run_id: str) -> IngestionRun:
        """取消尚未被 Worker 抢占的任务，并恢复关联文档的可用状态。"""
        run = self.get(db, run_id)
        if run is None:
            raise ValueError(f"入库任务不存在: {run_id}")
        if run.status != "pending":
            raise ValueError("只有 pending 状态的任务可以取消")

        document = db.get(KnowledgeDocument, run.document_id)
        run.status = "cancelled"
        run.completed_at = utc_now()
        run.updated_at = utc_now()
        if document is not None:
            if run.operation == "delete":
                # 删除未执行时保留原有索引；有分块即恢复 indexed，否则恢复 failed。
                document.status = "indexed" if document.chunk_count > 0 else "failed"
            else:
                document.status = "indexed" if document.chunk_count > 0 else "pending"
            document.updated_at = utc_now()
            db.add(document)
        db.add(run)
        db.commit()
        db.refresh(run)
        return run

    def retry_failed(self, db: Session, run_id: str) -> IngestionRun:
        """把已失败任务复制为新的待执行任务，保留原任务用于审计。"""
        failed_run = self.get(db, run_id)
        if failed_run is None:
            raise ValueError(f"入库任务不存在: {run_id}")
        if failed_run.status != "failed":
            raise ValueError("只有 failed 状态的任务可以人工重试")
        document = db.get(KnowledgeDocument, failed_run.document_id)
        if document is None:
            raise ValueError("入库任务关联的知识库文档不存在")
        new_run, _ = self.submit(
            db,
            document=document,
            operation=failed_run.operation,
            priority=failed_run.priority,
            max_retries=failed_run.max_retries,
            payload=failed_run.payload,
        )
        return new_run

    def claim_next(self, worker_id: str) -> IngestionRun | None:
        """使用 FOR UPDATE SKIP LOCKED 原子抢占一个可执行任务。"""
        statement = text(
            """
            WITH candidate AS (
                SELECT run_id
                FROM knowledge.ingestion_runs
                WHERE status = 'pending' AND available_at <= NOW()
                ORDER BY priority DESC, created_at ASC
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            UPDATE knowledge.ingestion_runs AS run
            SET status = 'running',
                worker_id = :worker_id,
                heartbeat_at = NOW(),
                started_at = COALESCE(started_at, NOW()),
                updated_at = NOW(),
                error_message = NULL
            FROM candidate
            WHERE run.run_id = candidate.run_id
            RETURNING run.*
            """
        )
        with get_db_session() as db:
            row = db.execute(statement, {"worker_id": worker_id}).mappings().first()
            if row is None:
                db.rollback()
                return None
            db.execute(
                text(
                    """
                    UPDATE knowledge.knowledge_documents
                    SET status = CASE
                            WHEN :operation = 'delete' THEN 'deleting'
                            ELSE 'indexing'
                        END,
                        error_message = NULL,
                        updated_at = NOW()
                    WHERE id = :document_id
                    """
                ),
                {
                    "document_id": row["document_id"],
                    "operation": row["operation"],
                },
            )
            db.commit()
            return IngestionRun.model_validate(dict(row))

    def heartbeat(self, run_id: str, worker_id: str) -> bool:
        """刷新运行中任务心跳；任务已转移或结束时返回 False。"""
        with get_db_session() as db:
            result = db.execute(
                text(
                    """
                    UPDATE knowledge.ingestion_runs
                    SET heartbeat_at = NOW(), updated_at = NOW()
                    WHERE run_id = :run_id
                      AND worker_id = :worker_id
                      AND status = 'running'
                    """
                ),
                {"run_id": run_id, "worker_id": worker_id},
            )
            db.commit()
            return bool(result.rowcount)

    def mark_completed(self, run_id: str, worker_id: str) -> None:
        """原子完成任务，并把文档状态更新为已索引。"""
        with get_db_session() as db:
            row = db.execute(
                text(
                    """
                    UPDATE knowledge.ingestion_runs
                    SET status = 'completed', completed_at = NOW(), updated_at = NOW(),
                        heartbeat_at = NOW(), error_message = NULL
                    WHERE run_id = :run_id AND worker_id = :worker_id AND status = 'running'
                    RETURNING document_id, operation
                    """
                ),
                {"run_id": run_id, "worker_id": worker_id},
            ).mappings().first()
            if row is None:
                db.rollback()
                raise RuntimeError(f"任务完成状态写入失败，任务可能已被其他 Worker 接管: {run_id}")
            db.execute(
                text(
                    """
                    UPDATE knowledge.knowledge_documents
                    SET status = CASE
                            WHEN :operation = 'delete' THEN 'deleted'
                            ELSE 'indexed'
                        END,
                        error_message = NULL,
                        indexed_at = CASE
                            WHEN :operation = 'delete' THEN NULL
                            ELSE NOW()
                        END,
                        chunk_count = CASE
                            WHEN :operation = 'delete' THEN 0
                            ELSE chunk_count
                        END,
                        updated_at = NOW()
                    WHERE id = :document_id
                    """
                ),
                {
                    "document_id": row["document_id"],
                    "operation": row["operation"],
                },
            )
            db.commit()

    def mark_failed_or_retry(
        self,
        run_id: str,
        worker_id: str,
        error_message: str,
        retry_delay_seconds: int,
    ) -> str:
        """记录执行失败；未超过次数时退避重排，否则终止任务。"""
        safe_error = error_message[:4000]
        with get_db_session() as db:
            run = db.get(IngestionRun, run_id)
            if run is None or run.status != "running" or run.worker_id != worker_id:
                raise RuntimeError(f"任务失败状态写入失败，任务所有权已变化: {run_id}")

            run.retry_count += 1
            run.error_message = safe_error
            run.updated_at = utc_now()
            if run.retry_count <= run.max_retries:
                run.status = "pending"
                run.available_at = utc_now() + timedelta(seconds=retry_delay_seconds * run.retry_count)
                run.worker_id = None
                run.heartbeat_at = None
                final_status = "pending"
                document_status = "deleting" if run.operation == "delete" else "pending"
            else:
                run.status = "failed"
                run.completed_at = utc_now()
                final_status = "failed"
                document_status = "failed"

            document = db.get(KnowledgeDocument, run.document_id)
            if document is not None:
                document.status = document_status
                document.error_message = safe_error
                document.updated_at = utc_now()
                db.add(document)
            db.add(run)
            db.commit()
            return final_status

    def recover_stale(self, stale_seconds: int, retry_delay_seconds: int) -> int:
        """扫描心跳超时任务，将其重新排队或标记为最终失败。"""
        statement = text(
            """
            SELECT run_id, worker_id
            FROM knowledge.ingestion_runs
            WHERE status = 'running'
              AND COALESCE(heartbeat_at, started_at, created_at)
                  < NOW() - (:stale_seconds * INTERVAL '1 second')
            """
        )
        recovered = 0
        with get_db_session() as db:
            stale_rows = list(db.execute(statement, {"stale_seconds": stale_seconds}).mappings())
        for row in stale_rows:
            try:
                self.mark_failed_or_retry(
                    row["run_id"],
                    row["worker_id"],
                    "Worker 心跳超时，任务已由队列恢复。",
                    retry_delay_seconds,
                )
                recovered += 1
            except RuntimeError:
                # 多实例可能同时发现僵尸任务，只有持有任务所有权的实例能成功恢复。
                continue
        if recovered:
            logger.warning("知识入库僵尸任务恢复完成: count=%s", recovered)
        return recovered


ingestion_queue_service = IngestionQueueService()
