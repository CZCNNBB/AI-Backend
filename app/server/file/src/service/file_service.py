import asyncio
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile
from sqlmodel import Session

from app.server.file.src.config.file_config import FileServiceConfig
from app.server.file.src.models.file_models import UploadedFileRecord
from app.server.file.src.parser.file_parser import FileContentBuildResult, FileParser
from app.server.file.src.repository.file_repository import FileRepository
from app.server.file.src.schemas.file_schemas import (
    FileDeleteResponse,
    FileParseResponse,
    FileReadResult,
    FileUploadResponse,
    UploadedFileView,
)


class FileService:
    """文件服务，负责上传、内容源构建、读取和删除文件。"""

    def __init__(
        self,
        repository: FileRepository | None = None,
        parser: FileParser | None = None,
        config: FileServiceConfig | None = None,
    ):
        """初始化文件服务。

        Args:
            repository: 文件数据访问层。
            parser: 文件内容源解析器。
            config: 文件服务环境配置，不传时从 .env 读取。
        """
        self.repository = repository or FileRepository()
        self.parser = parser or FileParser()
        self.config = config or FileServiceConfig.from_env()

    async def upload_files(self, db: Session, files: list[UploadFile]) -> FileUploadResponse:
        """上传文件并在当前请求内完成内容源构建。

        文件转换虽然属于上传请求的一部分，但 PDF 转 Markdown 会通过 asyncio.to_thread
        运行在线程池中，避免阻塞 FastAPI 的事件循环。

        Args:
            db: PostgreSQL Session。
            files: FastAPI 接收的上传文件列表。

        Returns:
            所有文件均已完成内容源构建后的文件视图列表。
        """
        if not files:
            raise RuntimeError("至少需要上传一个文件。")
        if len(files) > self.config.max_files_per_upload:
            raise RuntimeError(f"单次最多上传 {self.config.max_files_per_upload} 个文件。")

        self.get_upload_dir().mkdir(parents=True, exist_ok=True)
        uploaded: list[UploadedFileView] = []
        created_file_ids: list[str] = []
        total_size = 0

        try:
            for upload_file in files:
                file_id = uuid4().hex
                original_name = upload_file.filename or "unknown"
                extension = self.parser.normalize_extension(Path(original_name).suffix)
                file_dir = self.get_file_dir(file_id)
                original_path = file_dir / f"original{extension}"

                file_dir.mkdir(parents=True, exist_ok=False)
                try:
                    remaining_size = self.config.max_total_upload_bytes - total_size
                    if remaining_size <= 0:
                        raise RuntimeError(f"单次上传总大小不能超过 {self.config.max_total_upload_bytes} 字节。")

                    # 上传流和磁盘写入均为阻塞操作，放在线程池中避免卡住事件循环。
                    file_size = await asyncio.to_thread(
                        self.copy_upload_atomically,
                        upload_file,
                        original_path,
                        min(self.config.max_single_file_bytes, remaining_size),
                    )
                    total_size += file_size
                    record = UploadedFileRecord(
                        file_id=file_id,
                        original_name=original_name,
                        stored_name=original_path.name,
                        storage_path=str(original_path),
                        extension=extension,
                        mime_type=upload_file.content_type,
                        size_bytes=file_size,
                        status="uploaded",
                        content_type="pending",
                        conversion_status="pending",
                        extra_metadata={},
                        created_at=datetime.now(),
                        updated_at=datetime.now(),
                    )
                    self.repository.add(db, record)
                    created_file_ids.append(file_id)

                    # 必须在 HTTP 响应返回前完成转换，保证 Agent 拿到 file_id 后内容源已可用。
                    record = await self.ensure_content_source(db, file_id)
                    uploaded.append(self.to_view(record))
                finally:
                    upload_file.file.close()

            return FileUploadResponse(files=uploaded)
        except Exception:
            # 同一次上传中的任意文件失败时，回滚已经创建的文件记录和目录，保持结果一致。
            self.rollback_uploaded_files(db, created_file_ids)
            raise

    def get_upload_dir(self) -> Path:
        """获取文件上传根目录。"""
        if self.config.upload_dir:
            return Path(self.config.upload_dir).resolve()
        return Path(__file__).resolve().parents[5] / "data" / "uploads"

    def get_file_dir(self, file_id: str) -> Path:
        """获取指定 file_id 的独立文件目录。"""
        return self.get_upload_dir() / file_id

    def get_file(self, db: Session, file_id: str) -> UploadedFileView:
        """查询文件详情。"""
        return self.to_view(self.get_required_record(db, file_id))

    async def parse_file(self, db: Session, file_id: str, force: bool = False) -> FileParseResponse:
        """构建内容源并返回全文解析结果，仅供管理和调试接口使用。"""
        record = await self.ensure_content_source(db, file_id, force)
        content = "" if record.content_type == "image" else await self.read_record_content(record)
        return self.to_parse_response(record, content)

    async def ensure_content_source(self, db: Session, file_id: str, force: bool = False) -> UploadedFileRecord:
        """确保文件拥有可读取内容源；Outline 会在 Agent Run 中临时抽取。"""
        record = self.get_required_record(db, file_id)
        if not force and self.is_content_source_ready(record):
            return record

        record.conversion_status = "processing"
        record.conversion_error = None
        record.updated_at = datetime.now()
        self.repository.update(db, record)
        try:
            result = await self.parser.build_content_source(
                original_path=record.storage_path,
                extension=record.extension,
                markdown_path=str(self.get_file_dir(record.file_id) / "content.md"),
            )
            self.apply_content_build_result(record, result)
            record.updated_at = datetime.now()
            self.repository.update(db, record)
            return record
        except Exception as error:
            record.content_type = "unsupported"
            record.conversion_status = "failed"
            record.conversion_error = str(error)
            record.updated_at = datetime.now()
            self.repository.update(db, record)
            raise

    async def read_file_lines(
        self,
        db: Session,
        file_id: str,
        start_line: int | None = None,
        end_line: int | None = None,
    ) -> FileReadResult:
        """按行范围读取单个文件内容源。"""
        record = self.get_required_record(db, file_id)
        if not self.is_content_source_ready(record):
            return self.build_content_not_ready_result(record)
        if record.content_type == "image":
            return FileReadResult(
                file_id=record.file_id,
                original_name=record.original_name,
                content_type="image",
                message="当前未启用视觉识别，无法读取图片正文。",
            )

        lines = (await self.read_record_content(record)).splitlines()
        total_lines = len(lines)
        if not total_lines:
            return FileReadResult(
                file_id=record.file_id,
                original_name=record.original_name,
                content_type=record.content_type,
                message="文件已读取，但没有可用文本内容。",
            )

        actual_start = start_line or 1
        if actual_start < 1 or actual_start > total_lines:
            raise RuntimeError(f"start_line 必须在 1 到 {total_lines} 之间。")
        actual_end = end_line or min(actual_start + self.config.default_read_line_count - 1, total_lines)
        if actual_end < actual_start:
            raise RuntimeError("end_line 不能小于 start_line。")
        actual_end = min(actual_end, total_lines)

        output = "\n".join(f"{index}: {lines[index - 1]}" for index in range(actual_start, actual_end + 1))
        output, truncated = self.apply_output_limit(output)
        message = "本次读取结果过长，已截断。请缩小行范围后继续读取。" if truncated else None
        if message is None and actual_end < total_lines:
            message = f"当前展示第 {actual_start}-{actual_end} 行，文件共 {total_lines} 行。"
        return FileReadResult(
            file_id=record.file_id,
            original_name=record.original_name,
            content_type=record.content_type,
            content=output,
            start_line=actual_start,
            end_line=actual_end,
            total_lines=total_lines,
            truncated=truncated,
            message=message,
        )

    async def search_file_contents(
        self,
        db: Session,
        file_ids: list[str],
        keyword: str,
        max_results: int = 20,
        context_lines: int = 2,
    ) -> dict[str, object]:
        """在指定附件白名单中按关键词逐行检索内容。

        检索仅用于定位文件和行号，不返回完整正文。调用方应根据命中结果再使用
        ``read_file_lines`` 精读相关片段。

        Args:
            db: PostgreSQL Session。
            file_ids: 本次 Agent Run 允许访问的文件 ID 列表。
            keyword: 待检索的关键词，英文匹配时忽略大小写。
            max_results: 最多返回的命中数量，范围为 1 到 50。
            context_lines: 每个命中前后附带的上下文行数，范围为 0 到 5。

        Returns:
            包含命中片段、跳过文件和截断状态的检索结果。
        """
        cleaned_keyword = str(keyword or "").strip()
        if not cleaned_keyword:
            raise RuntimeError("keyword 不能为空。")

        # 工具参数允许模型给出建议值，但服务端必须限制范围，避免一次扫描结果撑大上下文。
        actual_max_results = min(max(int(max_results), 1), 50)
        actual_context_lines = min(max(int(context_lines), 0), 5)
        normalized_keyword = cleaned_keyword.casefold()
        matches: list[dict[str, object]] = []
        skipped_files: list[dict[str, str]] = []
        seen_file_ids: set[str] = set()
        truncated = False

        for raw_file_id in file_ids:
            file_id = str(raw_file_id or "").strip()
            if not file_id or file_id in seen_file_ids:
                continue
            seen_file_ids.add(file_id)

            record = self.repository.get_by_id(db, file_id)
            if record is None:
                skipped_files.append({"file_id": file_id, "reason": "文件不存在。"})
                continue
            if not self.is_content_source_ready(record):
                skipped_files.append({"file_id": file_id, "reason": self.get_content_not_ready_message(record)})
                continue
            if record.content_type == "image":
                skipped_files.append({"file_id": file_id, "reason": "当前未启用视觉识别，无法检索图片正文。"})
                continue

            lines = (await self.read_record_content(record)).splitlines()
            for line_number, line in enumerate(lines, start=1):
                if normalized_keyword not in line.casefold():
                    continue

                # 返回命中行附近的少量带行号上下文，让 Agent 能判断是否值得进一步精读。
                context_start = max(1, line_number - actual_context_lines)
                context_end = min(len(lines), line_number + actual_context_lines)
                context = "\n".join(
                    f"{index}: {lines[index - 1]}" for index in range(context_start, context_end + 1)
                )
                # 只有发现第 N+1 条命中时才标记截断；命中数刚好等于上限不代表结果被省略。
                if len(matches) >= actual_max_results:
                    truncated = True
                    break
                matches.append({
                    "file_id": record.file_id,
                    "file_name": record.original_name,
                    "line_number": line_number,
                    "snippet": line.strip(),
                    "context_start_line": context_start,
                    "context_end_line": context_end,
                    "context": context,
                })
            if truncated:
                break

        return {
            "keyword": cleaned_keyword,
            "matches": matches,
            "match_count": len(matches),
            "truncated": truncated,
            "skipped_files": skipped_files,
        }

    async def build_agent_file_summaries(self, db: Session, file_ids: list[str]) -> list[dict[str, object]]:
        """构建本次 Agent Run 使用的文件清单与临时 Outline。

        Outline 不落库。每个 Agent 组装出的 FileContextMiddleware 在首次模型调用时
        调用本方法，随后由中间件缓存结果供本次运行的后续模型调用复用。

        Args:
            db: PostgreSQL Session。
            file_ids: 本次运行可访问的文件 ID 列表。

        Returns:
            文件信息及本次运行临时生成的 Outline。
        """
        summaries: list[dict[str, object]] = []
        for raw_file_id in file_ids:
            file_id = str(raw_file_id or "").strip()
            if not file_id:
                continue
            record = self.repository.get_by_id(db, file_id)
            if record is None:
                summaries.append({"file_id": file_id, "status": "missing", "error": "文件不存在。"})
                continue

            outline = await self.build_runtime_outline(record)
            summaries.append({
                "file_id": record.file_id,
                "original_name": record.original_name,
                "extension": record.extension,
                "mime_type": record.mime_type,
                "size_bytes": record.size_bytes,
                "status": record.status,
                "content_type": record.content_type,
                "conversion_status": record.conversion_status,
                "outline": outline,
                "error": record.conversion_error,
            })
        return summaries

    def delete_files(self, db: Session, file_ids: list[str]) -> FileDeleteResponse:
        """删除文件记录及其 file_id 独立目录。"""
        records = self.repository.list_by_ids(db, file_ids)
        deleted_ids: list[str] = []
        for record in records:
            file_dir = self.get_file_dir(record.file_id)
            if file_dir.exists():
                shutil.rmtree(file_dir)
            deleted_ids.append(record.file_id)
        return FileDeleteResponse(
            deleted=self.repository.delete_by_ids(db, deleted_ids),
            file_ids=deleted_ids,
        )

    def copy_upload_atomically(self, upload_file: UploadFile, target_path: Path, max_bytes: int) -> int:
        """流式写入上传文件，并在写入过程中校验大小后原子提交。

        Args:
            upload_file: FastAPI 上传文件对象。
            target_path: 原始文件目标路径。
            max_bytes: 本次文件允许写入的最大字节数。

        Returns:
            实际写入的文件大小。

        Raises:
            RuntimeError: 文件超过大小限制时抛出。
        """
        temporary_path: Path | None = None
        total_size = 0
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=target_path.parent,
                prefix=".upload-",
                suffix=".part",
                delete=False,
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                while chunk := upload_file.file.read(self.config.upload_chunk_bytes):
                    total_size += len(chunk)
                    if total_size > max_bytes:
                        raise RuntimeError(f"上传文件超过限制 {max_bytes} 字节。")
                    temporary_file.write(chunk)
            temporary_path.replace(target_path)
            return total_size
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()

    def get_required_record(self, db: Session, file_id: str) -> UploadedFileRecord:
        """查询必须存在的文件记录。"""
        record = self.repository.get_by_id(db, file_id)
        if record is None:
            raise RuntimeError(f"文件不存在: {file_id}")
        return record

    async def build_runtime_outline(self, record: UploadedFileRecord) -> dict[str, object]:
        """为当前 Agent Run 从内容源临时抽取 Outline。

        Args:
            record: 已上传的文件记录。

        Returns:
            当前运行可注入模型上下文的 Outline。
        """
        if not self.is_content_source_ready(record):
            return self.build_content_not_ready_outline(record)
        if record.content_type == "image":
            return self.parser.ocr_service.build_placeholder_outline("image")

        # 读取文件内容源发生在工作线程中，正则扫描开销很小，不需要持久化缓存。
        content = await self.read_record_content(record)
        return self.parser.extract_outline(content)

    def build_content_not_ready_result(self, record: UploadedFileRecord) -> FileReadResult:
        """构建内容源尚未可读时的工具返回结果。

        Args:
            record: 尚未完成处理或处理失败的文件记录。

        Returns:
            告知 Agent 当前文件处理状态的读取结果。
        """
        return FileReadResult(
            file_id=record.file_id,
            original_name=record.original_name,
            content_type=record.content_type,
            message=self.get_content_not_ready_message(record),
        )

    def build_content_not_ready_outline(self, record: UploadedFileRecord) -> dict[str, object]:
        """构建后台处理未完成文件使用的占位 Outline。

        Args:
            record: 尚未完成处理或处理失败的文件记录。

        Returns:
            带处理状态说明的空 Outline。
        """
        return {
            "entries": [],
            "preview": [],
            "truncated": False,
            "message": self.get_content_not_ready_message(record),
        }

    def get_content_not_ready_message(self, record: UploadedFileRecord) -> str:
        """根据转换状态生成统一的文件不可读提示。

        Args:
            record: 文件数据库记录。

        Returns:
            适合 Agent 和前端展示的状态说明。
        """
        if record.conversion_status in {"pending", "processing"}:
            return "附件正在后台处理中，请等待内容源和 Outline 构建完成后再读取。"
        if record.conversion_status == "failed":
            return f"附件处理失败：{record.conversion_error or '未知原因'}"
        return f"附件当前不可读取，处理状态：{record.conversion_status}。"

    def is_content_source_ready(self, record: UploadedFileRecord) -> bool:
        """判断内容源缓存是否可复用。"""
        if record.conversion_status == "not_required":
            return record.content_type == "image" or bool(record.content_path and Path(record.content_path).exists())
        return record.conversion_status == "success" and bool(record.content_path and Path(record.content_path).exists())

    def apply_content_build_result(self, record: UploadedFileRecord, result: FileContentBuildResult) -> None:
        """将内容源构建结果写回数据库记录。"""
        record.content_path = result.content_path
        record.content_type = result.content_type
        record.conversion_status = result.conversion_status
        record.conversion_error = None
        record.converter_name = result.converter_name
        record.converted_at = datetime.now()

    async def read_record_content(self, record: UploadedFileRecord) -> str:
        """读取文件记录对应的内容源文本。"""
        return "" if not record.content_path else await self.parser.read_text_content(record.content_path)

    def apply_output_limit(self, content: str) -> tuple[str, bool]:
        """截断超长工具输出，避免单次读取耗尽模型上下文。"""
        if len(content) <= self.config.max_read_response_chars:
            return content, False
        head_size = self.config.max_read_response_chars // 2
        tail_size = self.config.max_read_response_chars - head_size
        omitted_size = len(content) - head_size - tail_size
        return (
            f"{content[:head_size]}\n\n"
            f"[... 已省略约 {omitted_size} 个字符，请缩小行范围后继续读取 ...]\n\n"
            f"{content[-tail_size:]}",
            True,
        )

    def rollback_uploaded_files(self, db: Session, file_ids: list[str]) -> None:
        """回滚同一次上传中已创建的数据库记录和独立目录。

        Args:
            db: PostgreSQL Session。
            file_ids: 已创建且需要回滚的文件 ID 列表。
        """
        for file_id in file_ids:
            file_dir = self.get_file_dir(file_id)
            if file_dir.exists():
                shutil.rmtree(file_dir)
        self.repository.delete_by_ids(db, file_ids)

    def to_view(self, record: UploadedFileRecord) -> UploadedFileView:
        """把数据库模型转换为接口视图。"""
        return UploadedFileView(
            file_id=record.file_id,
            original_name=record.original_name,
            stored_name=record.stored_name,
            extension=record.extension,
            mime_type=record.mime_type,
            size_bytes=record.size_bytes,
            status=record.status,
            content_type=record.content_type,
            conversion_status=record.conversion_status,
            converter_name=record.converter_name,
            created_at=record.created_at.isoformat() if record.created_at else None,
            updated_at=record.updated_at.isoformat() if record.updated_at else None,
        )

    def to_parse_response(self, record: UploadedFileRecord, content: str) -> FileParseResponse:
        """构建文件内容源接口响应。"""
        return FileParseResponse(
            file_id=record.file_id,
            original_name=record.original_name,
            content_type=record.content_type,
            content=content,
            content_length=len(content or ""),
            conversion_status=record.conversion_status,
            outline=(
                self.parser.ocr_service.build_placeholder_outline("image")
                if record.content_type == "image"
                else self.parser.extract_outline(content)
            ),
        )
