from datetime import datetime

from sqlmodel import Session, delete, select

from app.server.file.src.models.file_models import UploadedFileRecord


class FileRepository:
    """文件记录数据访问层。"""

    def add(self, db: Session, record: UploadedFileRecord) -> UploadedFileRecord:
        """在当前事务中新增文件记录，提交由上层业务边界负责。"""
        db.add(record)
        db.flush()
        db.refresh(record)
        return record

    def get_by_id(self, db: Session, file_id: str) -> UploadedFileRecord | None:
        """根据文件 ID 查询文件记录。"""
        statement = select(UploadedFileRecord).where(UploadedFileRecord.file_id == file_id)
        return db.exec(statement).first()

    def list_by_ids(self, db: Session, file_ids: list[str]) -> list[UploadedFileRecord]:
        """根据文件 ID 列表批量查询文件记录。"""
        if not file_ids:
            return []
        statement = select(UploadedFileRecord).where(UploadedFileRecord.file_id.in_(file_ids))
        return list(db.exec(statement).all())

    def update(self, db: Session, record: UploadedFileRecord) -> UploadedFileRecord:
        """在当前事务中更新文件记录，提交由上层业务边界负责。"""
        db.add(record)
        db.flush()
        db.refresh(record)
        return record

    def delete_by_ids(self, db: Session, file_ids: list[str]) -> int:
        """根据文件 ID 列表批量删除文件记录。"""
        if not file_ids:
            return 0
        statement = delete(UploadedFileRecord).where(UploadedFileRecord.file_id.in_(file_ids))
        result = db.exec(statement)
        db.flush()
        return int(result.rowcount or 0)

    def list_expired_temporary_files(
        self,
        db: Session,
        created_before: datetime,
        limit: int,
    ) -> list[UploadedFileRecord]:
        """锁定并返回一批已经超过保留期限的临时文件。

        Args:
            db: 当前清理事务使用的数据库会话。
            created_before: 创建时间早于该时间的文件才视为过期。
            limit: 单次最多领取的记录数量。

        Returns:
            当前事务成功领取的过期临时文件记录。
        """
        statement = (
            select(UploadedFileRecord)
            .where(
                UploadedFileRecord.is_long_term.is_(False),
                UploadedFileRecord.created_at <= created_before,
                UploadedFileRecord.conversion_status != "processing",
            )
            .order_by(UploadedFileRecord.created_at.asc())
            .limit(limit)
            # 多进程会分别启动清理器，SKIP LOCKED 可避免重复处理同一批文件。
            .with_for_update(skip_locked=True)
        )
        return list(db.exec(statement).all())
