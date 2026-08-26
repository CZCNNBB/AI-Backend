import asyncio
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pymupdf4llm

from app.server.file.src.logging_config import logger
from app.server.file.src.ocr.ocr_service import OcrService


@dataclass(frozen=True)
class FileContentBuildResult:
    """文件内容源构建结果。"""

    content_path: str | None
    content_type: str
    conversion_status: str
    converter_name: str | None


class FileParser:
    """文件解析器，负责构建 Agent 可按行读取的内容源。"""

    TEXT_EXTENSIONS = {
        ".txt", ".md", ".csv", ".json", ".log", ".yaml", ".yml", ".xml",
        ".html", ".htm", ".py", ".java", ".js", ".ts", ".tsx", ".jsx",
        ".vue", ".go", ".rs", ".c", ".h", ".cpp", ".cs", ".php", ".rb",
        ".sh", ".ps1", ".sql", ".ini", ".toml", ".properties",
    }
    IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff"}
    MARKDOWN_CONVERSION_EXTENSIONS = {".pdf"}

    MAX_OUTLINE_ENTRIES = 50
    OUTLINE_PREVIEW_LINES = 5

    def __init__(self, ocr_service: OcrService | None = None):
        """初始化文件解析器，并注入 OCR 能力边界。"""
        self.ocr_service = ocr_service or OcrService()

    async def build_content_source(
        self,
        original_path: str,
        extension: str,
        markdown_path: str,
    ) -> FileContentBuildResult:
        """根据文件类型构建 Agent 可读取的内容源。

        文本、代码不转换；PDF 优先使用 MinerU，健康检查失败时回退 pymupdf4llm；
        图片暂不做文本识别。

        Args:
            original_path: 上传原文件的磁盘路径。
            extension: 原始文件扩展名。
            markdown_path: PDF 转换后的 Markdown 缓存路径。

        Returns:
            内容源路径、类型、转换状态、转换器名称和 Outline。
        """
        source_path = Path(original_path)
        if not source_path.exists():
            raise RuntimeError(f"文件不存在: {original_path}")

        normalized_extension = self.normalize_extension(extension or source_path.suffix)
        if normalized_extension in self.IMAGE_EXTENSIONS:
            return FileContentBuildResult(
                None,
                "image",
                "not_required",
                None,
            )

        if normalized_extension in self.TEXT_EXTENSIONS:
            text = await self.read_text_content(str(source_path))
            return FileContentBuildResult(
                str(source_path),
                "original_text",
                "not_required",
                None,
            )

        if normalized_extension in self.MARKDOWN_CONVERSION_EXTENSIONS:
            converter_name = "pymupdf4llm"
            if await self.ocr_service.is_available():
                # MinerU 健康时统一使用 MinerU。任务失败或超时应明确暴露，不能静默切换解析器，
                # 否则平台会掩盖 MinerU 的真实故障并产生难以解释的解析质量差异。
                markdown = await self.ocr_service.recognize_to_markdown(str(source_path))
                converter_name = "mineru"
                logger.info(
                    "PDF 解析器选择完成: file_name=%r converter=mineru",
                    source_path.name,
                )
            else:
                # 健康检查失败只代表本次无法使用远端 MinerU，本地解析器在线程池中执行，
                # 避免同步 PDF 解析阻塞 FastAPI 事件循环。
                markdown = await asyncio.to_thread(self.convert_pdf_to_markdown, source_path)
                logger.warning(
                    "PDF 解析器已回退: file_name=%r converter=pymupdf4llm",
                    source_path.name,
                )

            target_path = Path(markdown_path)
            await asyncio.to_thread(self.write_text_atomically, target_path, markdown)
            logger.info(
                "PDF Markdown 缓存写入完成: file_name=%r converter=%s markdown_chars=%s",
                source_path.name,
                converter_name,
                len(markdown),
            )
            return FileContentBuildResult(
                str(target_path),
                "markdown",
                "success",
                converter_name,
            )

        raise RuntimeError(f"暂不支持该文件类型的内容转换: {normalized_extension or 'unknown'}")

    async def read_text_content(self, file_path: str) -> str:
        """按常见编码读取文本类内容源。

        Args:
            file_path: 内容源文件路径。

        Returns:
            解码后的文本内容。
        """
        return await asyncio.to_thread(self.read_text_file, Path(file_path))

    def normalize_extension(self, extension: str) -> str:
        """标准化文件扩展名。

        Args:
            extension: 包含或不包含点号的文件扩展名。

        Returns:
            小写且包含点号的扩展名。
        """
        cleaned = (extension or "").strip().lower()
        return cleaned if not cleaned or cleaned.startswith(".") else f".{cleaned}"

    def convert_pdf_to_markdown(self, source_path: Path) -> str:
        """在 MinerU 健康检查失败时，使用 pymupdf4llm 转换 PDF。

        Args:
            source_path: PDF 原文件路径。

        Returns:
            转换得到的 Markdown 文本。
        """
        # 回退解析器不启用本地 OCR；扫描型 PDF 应由 MinerU 处理，避免环境差异导致隐式行为。
        markdown = pymupdf4llm.to_markdown(str(source_path), use_ocr=False)
        if not isinstance(markdown, str) or not markdown.strip():
            raise RuntimeError(
                "PDF 转 Markdown 后没有得到可用文本内容。可能是扫描型 PDF；"
                + self.ocr_service.get_unavailable_message("scanned_pdf")
            )
        return markdown

    def read_text_file(self, path: Path) -> str:
        """读取文本文件并兼容常见编码。

        Args:
            path: 待读取文件路径。

        Returns:
            文件文本内容。
        """
        for encoding in ("utf-8", "utf-8-sig", "gb18030", "gbk"):
            try:
                return path.read_text(encoding=encoding)
            except UnicodeDecodeError:
                continue
        return path.read_text(encoding="utf-8", errors="ignore")

    def write_text_atomically(self, path: Path, content: str) -> None:
        """原子写入转换后的 Markdown 缓存。

        Args:
            path: Markdown 目标路径。
            content: 要写入的内容。
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                dir=path.parent,
                prefix=".content-",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                temporary_file.write(content)
                temporary_path = Path(temporary_file.name)
            temporary_path.replace(path)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()

    def extract_outline(self, content: str) -> dict[str, Any]:
        """从 Markdown 或纯文本中抽取标题目录与预览。

        Args:
            content: 内容源文本。

        Returns:
            包含目录、全文行数、标题统计和预览的 Outline 字典。
        """
        content_lines = (content or "").splitlines()
        entries: list[dict[str, Any]] = []
        total_heading_count = 0
        for line_number, line in enumerate(content_lines, start=1):
            matched = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
            if matched is None:
                continue

            # 统计完整标题数量，但只保留固定数量的目录条目，避免长文档撑大模型上下文。
            total_heading_count += 1
            if len(entries) >= self.MAX_OUTLINE_ENTRIES:
                continue
            entries.append({
                "level": len(matched.group(1)),
                "title": matched.group(2).strip(),
                "line_number": line_number,
            })

        preview = []
        if not entries:
            preview = [line.strip() for line in content_lines if line.strip()][:self.OUTLINE_PREVIEW_LINES]
        return {
            "entries": entries,
            "preview": preview,
            "total_lines": len(content_lines),
            "total_heading_count": total_heading_count,
            "omitted_heading_count": max(total_heading_count - len(entries), 0),
            "truncated": total_heading_count > len(entries),
        }

    def empty_outline(self) -> dict[str, Any]:
        """构建没有文本内容时使用的空 Outline。"""
        return {
            "entries": [],
            "preview": [],
            "total_lines": 0,
            "total_heading_count": 0,
            "omitted_heading_count": 0,
            "truncated": False,
        }
