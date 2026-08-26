import asyncio
import logging
import mimetypes
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from app.server.file.src.ocr.mineru_config import MinerUConfig


logger = logging.getLogger("ai_backend.file.ocr")


class OcrService:
    """MinerU OCR 客户端，负责健康检查、任务提交、轮询和 Markdown 提取。"""

    def __init__(
        self,
        config: MinerUConfig | None = None,
        client_factory: Callable[[], httpx.AsyncClient] | None = None,
    ) -> None:
        """初始化 MinerU OCR 服务。

        Args:
            config: MinerU 服务配置，不传时从环境变量读取。
            client_factory: HTTP 客户端工厂，主要用于测试注入 MockTransport。
        """
        self.config = config or MinerUConfig.from_env()
        self._client_factory = client_factory or self._create_default_client

    async def is_available(self) -> bool:
        """调用 MinerU 健康接口，判断本次解析是否可以使用 MinerU。

        Returns:
            配置已启用且健康接口返回 ``status=healthy`` 时返回 True。
        """
        if not self.config.enabled or not self.config.base_url:
            logger.info("MinerU 健康检查跳过: enabled=%s", self.config.enabled)
            return False

        logger.info("MinerU 健康检查开始: base_url=%s", self.config.base_url)
        try:
            async with self._client_factory() as client:
                response = await client.get(
                    "/health",
                    timeout=self.config.health_timeout_seconds,
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError, TypeError) as error:
            # 健康检查只决定是否启用 MinerU；失败时由 FileParser 自动走本地回退解析器。
            logger.warning("MinerU 健康检查失败，将回退 pymupdf4llm: %s", error)
            return False

        is_healthy = isinstance(payload, dict) and str(payload.get("status") or "").lower() == "healthy"
        if not is_healthy:
            status = payload.get("status") if isinstance(payload, dict) else None
            logger.warning("MinerU 健康状态异常，将回退 pymupdf4llm: status=%s", status or "未知")
        else:
            logger.info(
                "MinerU 健康检查通过: version=%s queued_tasks=%s processing_tasks=%s",
                payload.get("version") or "未知",
                payload.get("queued_tasks", "未知"),
                payload.get("processing_tasks", "未知"),
            )
        return is_healthy

    def get_unavailable_message(self, file_kind: str) -> str:
        """构建 MinerU 与本地解析器均无法处理时的统一提示。

        Args:
            file_kind: 文件类型，例如 image 或 scanned_pdf。

        Returns:
            OCR 未启用说明。
        """
        return f"当前 {file_kind} 无法提取可用文本，请检查 MinerU 服务和原始文件内容。"

    def build_placeholder_outline(self, file_kind: str) -> dict[str, object]:
        """构建 OCR 未启用文件使用的占位 Outline。

        Args:
            file_kind: 文件类型，例如 image。

        Returns:
            带 OCR 状态和提示信息的空 Outline。
        """
        return {
            "entries": [],
            "preview": [],
            "total_lines": 0,
            "total_heading_count": 0,
            "omitted_heading_count": 0,
            "truncated": False,
            "ocr_status": "not_enabled",
            "message": self.get_unavailable_message(file_kind),
        }

    async def recognize_to_markdown(self, file_path: str) -> str:
        """向 MinerU 提交单文件任务，并等待解析完成后返回 Markdown。

        Args:
            file_path: 待 OCR 的原始文件路径。

        Returns:
            MinerU 生成的 Markdown 内容。

        Raises:
            RuntimeError: 任务提交、轮询、解析结果读取失败或任务超时时抛出。
        """
        source_path = Path(file_path)
        if not source_path.is_file():
            raise RuntimeError(f"MinerU 待解析文件不存在: {file_path}")

        started_at = time.perf_counter()
        task_id: str | None = None
        logger.info(
            "MinerU 文件解析开始: file_name=%r size_bytes=%s",
            source_path.name,
            source_path.stat().st_size,
        )
        try:
            async with self._client_factory() as client:
                task_id = await self._submit_task(client, source_path)
                await self._wait_for_completion(client, task_id)
                markdown = await self._fetch_markdown(client, task_id, source_path)
        except Exception as error:
            elapsed_seconds = time.perf_counter() - started_at
            logger.exception(
                "MinerU 文件解析失败: file_name=%r task_id=%s elapsed_seconds=%.3f reason=%s",
                source_path.name,
                task_id or "尚未创建",
                elapsed_seconds,
                error,
            )
            raise

        elapsed_seconds = time.perf_counter() - started_at
        logger.info(
            "MinerU 文件解析完成: file_name=%r task_id=%s markdown_chars=%s elapsed_seconds=%.3f",
            source_path.name,
            task_id,
            len(markdown),
            elapsed_seconds,
        )
        return markdown

    def _create_default_client(self) -> httpx.AsyncClient:
        """创建一次解析流程使用的默认异步 HTTP 客户端。

        Returns:
            已配置 MinerU 基础地址和请求超时的 AsyncClient。
        """
        return httpx.AsyncClient(
            base_url=self.config.base_url,
            timeout=self.config.request_timeout_seconds,
        )

    async def _submit_task(self, client: httpx.AsyncClient, source_path: Path) -> str:
        """上传单个文件并返回 MinerU 任务 ID。

        Args:
            client: 当前解析流程复用的 HTTP 客户端。
            source_path: 待解析的本地文件。

        Returns:
            MinerU 返回的非空 task_id。
        """
        mime_type = mimetypes.guess_type(source_path.name)[0] or "application/octet-stream"
        form_data = {
            "lang_list": "ch",
            "backend": "pipeline",
            "parse_method": "auto",
            "formula_enable": "true",
            "table_enable": "true",
            "image_analysis": "false",
            "return_md": "true",
            "return_images": "false",
            "response_format_zip": "false",
        }

        # 文件句柄只在请求发送期间保持打开，提交完成后立即释放，避免长期占用上传文件。
        with source_path.open("rb") as source_file:
            response = await client.post(
                "/tasks",
                data=form_data,
                files={"files": (source_path.name, source_file, mime_type)},
            )
        response.raise_for_status()
        payload = self._read_json_object(response, "MinerU 提交任务")
        task_id = str(payload.get("task_id") or "").strip()
        if not task_id:
            raise RuntimeError(f"MinerU 提交任务响应缺少 task_id: {payload}")
        logger.info(
            "MinerU 解析任务提交成功: file_name=%r task_id=%s status=%s queued_ahead=%s",
            source_path.name,
            task_id,
            payload.get("status") or "未知",
            payload.get("queued_ahead", "未知"),
        )
        return task_id

    async def _wait_for_completion(self, client: httpx.AsyncClient, task_id: str) -> None:
        """轮询 MinerU 任务状态，直到成功、失败或超时。

        Args:
            client: 当前解析流程复用的 HTTP 客户端。
            task_id: MinerU 任务 ID。
        """
        deadline = time.monotonic() + self.config.task_timeout_seconds
        previous_status: str | None = None
        while True:
            response = await client.get(f"/tasks/{task_id}")
            response.raise_for_status()
            payload = self._read_json_object(response, "MinerU 查询任务")
            status = str(payload.get("status") or "").strip().lower()

            # 只在任务状态发生变化时输出日志，避免固定轮询间隔产生大量重复记录。
            if status != previous_status:
                logger.info(
                    "MinerU 解析任务状态变化: task_id=%s status=%s queued_ahead=%s",
                    task_id,
                    status or "未知",
                    payload.get("queued_ahead", "未知"),
                )
                previous_status = status

            if status == "completed":
                return
            if status == "failed":
                error_message = str(payload.get("error") or "未知错误")
                raise RuntimeError(f"MinerU 解析任务失败: task_id={task_id}, error={error_message}")
            if status not in {"pending", "processing"}:
                raise RuntimeError(f"MinerU 返回未知任务状态: task_id={task_id}, status={status or 'empty'}")

            remaining_seconds = deadline - time.monotonic()
            if remaining_seconds <= 0:
                raise RuntimeError(
                    f"MinerU 解析任务超时: task_id={task_id}, "
                    f"timeout={self.config.task_timeout_seconds}秒"
                )

            # 最后一次等待不超过剩余超时时间，避免轮询间隔让总等待明显超出配置。
            await asyncio.sleep(min(self.config.poll_interval_seconds, remaining_seconds))

    async def _fetch_markdown(
        self,
        client: httpx.AsyncClient,
        task_id: str,
        source_path: Path,
    ) -> str:
        """读取完成任务的结果，并提取单文件 Markdown。

        Args:
            client: 当前解析流程复用的 HTTP 客户端。
            task_id: 已完成的 MinerU 任务 ID。
            source_path: 原始文件路径，用于优先匹配结果名称。

        Returns:
            非空 Markdown 文本。
        """
        response = await client.get(f"/tasks/{task_id}/result")
        response.raise_for_status()
        payload = self._read_json_object(response, "MinerU 获取结果")
        raw_results = payload.get("results")
        if not isinstance(raw_results, dict) or not raw_results:
            raise RuntimeError(f"MinerU 结果缺少 results: task_id={task_id}")

        result_item = self._select_result_item(raw_results, source_path)
        markdown = result_item.get("md_content") if isinstance(result_item, dict) else None
        if not isinstance(markdown, str) or not markdown.strip():
            raise RuntimeError(f"MinerU 结果缺少有效 md_content: task_id={task_id}")
        logger.info(
            "MinerU 解析结果读取完成: task_id=%s result_count=%s markdown_chars=%s",
            task_id,
            len(raw_results),
            len(markdown),
        )
        return markdown

    def _select_result_item(self, results: dict[str, Any], source_path: Path) -> dict[str, Any]:
        """从 MinerU results 中选择当前单文件对应的结果对象。

        Args:
            results: MinerU 返回的文件名到结果对象映射。
            source_path: 原始文件路径。

        Returns:
            选中的结果对象。
        """
        candidate_names = {source_path.name, source_path.stem}
        for result_name, result_item in results.items():
            if str(result_name) in candidate_names and isinstance(result_item, dict):
                return result_item

        # 当前平台每个任务只提交一个文件，因此名称未完全匹配时可以安全使用唯一结果。
        if len(results) == 1:
            only_item = next(iter(results.values()))
            if isinstance(only_item, dict):
                return only_item
        raise RuntimeError(f"MinerU 结果无法匹配原始文件: file={source_path.name}, results={list(results)}")

    @staticmethod
    def _read_json_object(response: httpx.Response, action: str) -> dict[str, Any]:
        """读取 HTTP JSON 对象，并把协议错误转换为清晰的运行异常。

        Args:
            response: MinerU HTTP 响应。
            action: 当前请求动作，用于错误信息定位。

        Returns:
            JSON 对象。
        """
        try:
            payload = response.json()
        except ValueError as error:
            raise RuntimeError(f"{action}响应不是有效 JSON") from error
        if not isinstance(payload, dict):
            raise RuntimeError(f"{action}响应必须是 JSON 对象")
        return payload
