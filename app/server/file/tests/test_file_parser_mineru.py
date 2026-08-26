import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from app.server.file.src.parser.file_parser import FileParser


class FileParserMinerUTests(unittest.IsolatedAsyncioTestCase):
    """验证 PDF 的 MinerU 优先和 pymupdf4llm 回退策略。"""

    async def test_pdf_uses_mineru_when_health_check_passes(self) -> None:
        """MinerU 健康时应保存 MinerU Markdown 并记录转换器名称。"""
        ocr_service = MagicMock()
        ocr_service.is_available = AsyncMock(return_value=True)
        ocr_service.recognize_to_markdown = AsyncMock(return_value="# MinerU\n\n解析正文")
        parser = FileParser(ocr_service=ocr_service)

        with tempfile.TemporaryDirectory() as temporary_dir:
            source_path = Path(temporary_dir) / "source.pdf"
            markdown_path = Path(temporary_dir) / "content.md"
            source_path.write_bytes(b"fake pdf content")

            result = await parser.build_content_source(
                original_path=str(source_path),
                extension=".pdf",
                markdown_path=str(markdown_path),
            )

            self.assertEqual(markdown_path.read_text(encoding="utf-8"), "# MinerU\n\n解析正文")

        self.assertEqual(result.converter_name, "mineru")
        ocr_service.recognize_to_markdown.assert_awaited_once_with(str(source_path))

    async def test_pdf_falls_back_when_health_check_fails(self) -> None:
        """MinerU 健康检查失败时应在线程中调用 pymupdf4llm。"""
        ocr_service = MagicMock()
        ocr_service.is_available = AsyncMock(return_value=False)
        ocr_service.recognize_to_markdown = AsyncMock()
        parser = FileParser(ocr_service=ocr_service)

        with tempfile.TemporaryDirectory() as temporary_dir:
            source_path = Path(temporary_dir) / "source.pdf"
            markdown_path = Path(temporary_dir) / "content.md"
            source_path.write_bytes(b"fake pdf content")

            with self.assertLogs("ai_backend.file", level="WARNING") as captured_logs:
                with patch(
                    "app.server.file.src.parser.file_parser.pymupdf4llm.to_markdown",
                    return_value="# 本地回退\n\n解析正文",
                ) as local_converter:
                    result = await parser.build_content_source(
                        original_path=str(source_path),
                        extension="pdf",
                        markdown_path=str(markdown_path),
                    )

            self.assertEqual(markdown_path.read_text(encoding="utf-8"), "# 本地回退\n\n解析正文")

        self.assertEqual(result.converter_name, "pymupdf4llm")
        local_converter.assert_called_once_with(str(source_path), use_ocr=False)
        ocr_service.recognize_to_markdown.assert_not_awaited()
        self.assertIn("PDF 解析器已回退", "\n".join(captured_logs.output))

    async def test_mineru_task_failure_does_not_silently_fallback(self) -> None:
        """健康检查通过后的 MinerU 任务错误应直接交给上层记录。"""
        ocr_service = MagicMock()
        ocr_service.is_available = AsyncMock(return_value=True)
        ocr_service.recognize_to_markdown = AsyncMock(side_effect=RuntimeError("MinerU 任务失败"))
        parser = FileParser(ocr_service=ocr_service)

        with tempfile.TemporaryDirectory() as temporary_dir:
            source_path = Path(temporary_dir) / "source.pdf"
            source_path.write_bytes(b"fake pdf content")

            with patch("app.server.file.src.parser.file_parser.pymupdf4llm.to_markdown") as local_converter:
                with self.assertRaisesRegex(RuntimeError, "MinerU 任务失败"):
                    await parser.build_content_source(
                        original_path=str(source_path),
                        extension=".pdf",
                        markdown_path=str(Path(temporary_dir) / "content.md"),
                    )

        local_converter.assert_not_called()


if __name__ == "__main__":
    unittest.main()
