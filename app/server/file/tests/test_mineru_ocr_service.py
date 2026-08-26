import tempfile
import unittest
from pathlib import Path

import httpx

from app.server.file.src.ocr.mineru_config import MinerUConfig
from app.server.file.src.ocr.ocr_service import OcrService


def build_test_config() -> MinerUConfig:
    """构建不会读取开发环境变量的 MinerU 测试配置。"""
    return MinerUConfig(
        enabled=True,
        base_url="http://mineru.test",
        health_timeout_seconds=1.0,
        request_timeout_seconds=1.0,
        task_timeout_seconds=1.0,
        poll_interval_seconds=0.001,
    )


class MinerUOcrServiceTests(unittest.IsolatedAsyncioTestCase):
    """验证 MinerU 健康检查和异步任务协议。"""

    async def test_health_check_accepts_healthy_response(self) -> None:
        """健康接口返回 healthy 时应允许本次 PDF 使用 MinerU。"""
        transport = httpx.MockTransport(
            lambda request: httpx.Response(200, json={"status": "healthy", "version": "3.4.5"})
        )
        service = OcrService(
            config=build_test_config(),
            client_factory=lambda: httpx.AsyncClient(base_url="http://mineru.test", transport=transport),
        )

        with self.assertLogs("ai_backend.file.ocr", level="INFO") as captured_logs:
            self.assertTrue(await service.is_available())

        combined_logs = "\n".join(captured_logs.output)
        self.assertIn("MinerU 健康检查开始", combined_logs)
        self.assertIn("MinerU 健康检查通过", combined_logs)

    async def test_health_check_failure_returns_false(self) -> None:
        """健康请求连接失败时应返回 False，让文件解析器走本地回退。"""
        def raise_connection_error(request: httpx.Request) -> httpx.Response:
            """模拟无法连接 MinerU 服务。"""
            raise httpx.ConnectError("connection refused", request=request)

        transport = httpx.MockTransport(raise_connection_error)
        service = OcrService(
            config=build_test_config(),
            client_factory=lambda: httpx.AsyncClient(base_url="http://mineru.test", transport=transport),
        )

        with self.assertLogs("ai_backend.file.ocr", level="WARNING") as captured_logs:
            self.assertFalse(await service.is_available())

        self.assertIn("将回退 pymupdf4llm", "\n".join(captured_logs.output))

    async def test_recognize_to_markdown_completes_async_task(self) -> None:
        """客户端应提交文件、轮询任务并从唯一结果中提取 md_content。"""
        status_call_count = 0

        def handle_request(request: httpx.Request) -> httpx.Response:
            """按照 MinerU 协议返回提交、轮询和结果响应。"""
            nonlocal status_call_count
            if request.method == "POST" and request.url.path == "/tasks":
                content_type = request.headers.get("content-type", "")
                self.assertIn("multipart/form-data", content_type)
                return httpx.Response(202, json={"task_id": "task-001", "status": "pending"})
            if request.method == "GET" and request.url.path == "/tasks/task-001":
                status_call_count += 1
                status = "pending" if status_call_count == 1 else "completed"
                return httpx.Response(200, json={"task_id": "task-001", "status": status})
            if request.method == "GET" and request.url.path == "/tasks/task-001/result":
                return httpx.Response(
                    200,
                    json={"results": {"sample": {"md_content": "# MinerU 结果\n\n正文"}}},
                )
            return httpx.Response(404, json={"error": "not found"})

        transport = httpx.MockTransport(handle_request)
        service = OcrService(
            config=build_test_config(),
            client_factory=lambda: httpx.AsyncClient(base_url="http://mineru.test", transport=transport),
        )

        with tempfile.TemporaryDirectory() as temporary_dir:
            source_path = Path(temporary_dir) / "sample.pdf"
            source_path.write_bytes(b"fake pdf content")
            with self.assertLogs("ai_backend.file.ocr", level="INFO") as captured_logs:
                markdown = await service.recognize_to_markdown(str(source_path))

        self.assertEqual(markdown, "# MinerU 结果\n\n正文")
        self.assertEqual(status_call_count, 2)
        combined_logs = "\n".join(captured_logs.output)
        self.assertIn("MinerU 解析任务提交成功", combined_logs)
        self.assertIn("status=pending", combined_logs)
        self.assertIn("status=completed", combined_logs)
        self.assertIn("MinerU 文件解析完成", combined_logs)

    async def test_failed_task_raises_clear_error(self) -> None:
        """MinerU 健康后任务失败时应暴露服务端 error，不应静默回退。"""
        def handle_request(request: httpx.Request) -> httpx.Response:
            """模拟提交成功但解析失败的任务。"""
            if request.method == "POST":
                return httpx.Response(202, json={"task_id": "task-failed"})
            if request.url.path == "/tasks/task-failed":
                return httpx.Response(200, json={"status": "failed", "error": "模型加载失败"})
            return httpx.Response(404)

        transport = httpx.MockTransport(handle_request)
        service = OcrService(
            config=build_test_config(),
            client_factory=lambda: httpx.AsyncClient(base_url="http://mineru.test", transport=transport),
        )

        with tempfile.TemporaryDirectory() as temporary_dir:
            source_path = Path(temporary_dir) / "sample.pdf"
            source_path.write_bytes(b"fake pdf content")
            with self.assertLogs("ai_backend.file.ocr", level="ERROR") as captured_logs:
                with self.assertRaisesRegex(RuntimeError, "模型加载失败"):
                    await service.recognize_to_markdown(str(source_path))

        self.assertIn("MinerU 文件解析失败", "\n".join(captured_logs.output))


if __name__ == "__main__":
    unittest.main()
