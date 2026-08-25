from sqlmodel import Session, delete, select

from app.server.file.src.models.file_models import UploadedFileRecord


class FileRepository:
    """文件记录数据访问层。"""

    def add(self, db: Session, record: UploadedFileRecord) -> UploadedFileRecord:
        """新增文件记录。"""
        db.add(record)
        db.commit()
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
        """更新文件记录。"""
        db.add(record)
        db.commit()
        db.refresh(record)
        return record

    def delete_by_ids(self, db: Session, file_ids: list[str]) -> int:
        """根据文件 ID 列表批量删除文件记录。"""
        if not file_ids:
            return 0
        statement = delete(UploadedFileRecord).where(UploadedFileRecord.file_id.in_(file_ids))
        result = db.exec(statement)
        db.commit()
        return int(result.rowcount or 0)
