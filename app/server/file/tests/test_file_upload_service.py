import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from starlette.datastructures import Headers, UploadFile

from app.server.file.src.config.file_config import FileServiceConfig
from app.server.file.src.service.file_service import FileService


class FileUploadServiceTests(unittest.IsolatedAsyncioTestCase):
    """验证文件上传与内容解析之间的职责边界。"""

    async def test_upload_only_saves_original_file_and_returns_file_id(self) -> None:
        """上传接口必须保持 conversion_status=pending，不能触发解析器。"""
        repository = MagicMock()
        parser = MagicMock()
        parser.normalize_extension.return_value = ".pdf"
        parser.build_content_source = AsyncMock()

        with tempfile.TemporaryDirectory() as temporary_dir:
            config = FileServiceConfig(
                upload_dir=temporary_dir,
                max_files_per_upload=10,
                max_single_file_bytes=10 * 1024 * 1024,
                max_total_upload_bytes=20 * 1024 * 1024,
                upload_chunk_bytes=1024,
                default_read_line_count=200,
                max_read_response_chars=24_000,
            )
            service = FileService(repository=repository, parser=parser, config=config)
            upload_file = UploadFile(
                filename="测试文档.pdf",
                file=io.BytesIO(b"fake pdf content"),
                headers=Headers({"content-type": "application/pdf"}),
            )

            response = await service.upload_files(MagicMock(), [upload_file], is_long_term=False)

            self.assertEqual(len(response.file_ids), 1)
            saved_record = repository.add.call_args.args[1]
            self.assertEqual(response.file_ids[0], saved_record.file_id)
            self.assertFalse(saved_record.is_long_term)
            self.assertEqual(saved_record.content_type, "pending")
            self.assertEqual(saved_record.conversion_status, "pending")
            self.assertIsNone(saved_record.content_path)
            self.assertEqual(Path(saved_record.storage_path).read_bytes(), b"fake pdf content")

        # 上传结束后解析器必须完全没有被调用，后续业务场景再根据 file_id 显式处理。
        parser.build_content_source.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
