from typing import Any

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlmodel import Session

from app.common.db.postgres_db import get_postgres_engine
from app.common.schemas.result import Result
from app.server.file.src.schemas.file_schemas import (
    FileDeleteRequest,
    FileDeleteResponse,
    FileDetailRequest,
    FileParseRequest,
    FileParseResponse,
    FileUploadResponse,
    UploadedFileView,
)
from app.server.file.src.service.file_service import FileService


router = APIRouter(prefix="/file")
file_service = FileService()


@router.get("/health", response_model=Result[dict[str, Any]], summary="文件服务健康检查")
def file_health():
    """检查文件服务是否已经挂载。"""
    return Result.success({"service": "file", "status": "ok"})


@router.post("/upload", response_model=Result[FileUploadResponse], summary="上传文件")
async def upload_files(
    files: list[UploadFile] = File(...),
    is_long_term: bool = Form(..., description="是否长期保存：知识库传 true，Agent 附件传 false"),
    db: Session = Depends(get_postgres_engine),
):
    """保存原始文件并返回 file_id，由调用场景明确指定是否长期保存。"""
    return Result.success(await file_service.upload_files(db, files, is_long_term))


@router.post("/detail", response_model=Result[UploadedFileView], summary="查询文件详情")
def get_file_detail(request: FileDetailRequest, db: Session = Depends(get_postgres_engine)):
    """根据文件 ID 查询文件详情。"""
    return Result.success(file_service.get_file(db, request.file_id))


@router.post("/parse", response_model=Result[FileParseResponse], summary="构建文件内容源")
async def parse_file(request: FileParseRequest, db: Session = Depends(get_postgres_engine)):
    """根据文件 ID 构建可读内容源，并返回解析文本和 Outline。"""
    return Result.success(await file_service.parse_file(db, request.file_id, request.force))


@router.post("/delete", response_model=Result[FileDeleteResponse], summary="删除文件")
def delete_files(request: FileDeleteRequest, db: Session = Depends(get_postgres_engine)):
    """删除文件记录和 file_id 独立目录。"""
    return Result.success(file_service.delete_files(db, request.file_ids))
