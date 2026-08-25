"""HTTP Rerank 模型服务客户端。"""

import asyncio
from typing import Any

import httpx

from app.server.agent.src.model.constants import (
    DEFAULT_MODEL_MAX_RETRIES,
    DEFAULT_MODEL_TIMEOUT_SECONDS,
    MODEL_RETRYABLE_STATUS_CODES,
)
from app.server.agent.src.model.resource import ModelRuntimeResource, resolve_model_resource
from app.server.knowledge.src.config import knowledge_config as settings
from app.server.knowledge.src.retrieval.exceptions import (
    RetrievalDependencyError,
    RetrievalValidationError,
)
from app.server.knowledge.src.retrieval.schemas import RerankConfig


class RerankClient:
    """通过 model_configs 中的 Rerank 模型配置执行候选重排。"""

    def __init__(self) -> None:
        """创建可复用的异步 HTTP 连接池。"""
        limits = httpx.Limits(
            max_keepalive_connections=settings.http_max_keepalive_connections,
            max_connections=settings.http_max_connections,
        )
        self._client = httpx.AsyncClient(limits=limits)

    async def close(self) -> None:
        """关闭 Rerank HTTP 连接池。"""
        await self._client.aclose()

    async def health_check(self, model_code: str) -> int:
        """调用指定 Rerank 模型执行真实健康检查。"""
        ordered_indices = await self.rerank(
            query="retrieval rerank health check",
            documents=[
                "retrieval rerank health check document",
                "unrelated candidate document",
            ],
            config=RerankConfig(enable=True, model_code=model_code),
        )
        return len(ordered_indices)

    async def rerank(
        self,
        *,
        query: str,
        documents: list[str],
        config: RerankConfig,
        timeout_seconds: int = DEFAULT_MODEL_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MODEL_MAX_RETRIES,
    ) -> list[int]:
        """调用明确指定的 Rerank model_code 并返回候选排序下标。"""
        if not documents:
            return []
        if not config.model_code:
            raise RetrievalValidationError("启用 Rerank 时必须提供 model_code")

        resource = resolve_model_resource(config.model_code, "rerank")
        payload = {
            "model": resource.model_name,
            "query": query,
            "documents": documents,
        }
        response_data = await self._post_with_retry(
            resource=resource,
            payload=payload,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
        )
        return self._parse_response(
            response_data=response_data,
            document_count=len(documents),
        )

    async def _post_with_retry(
        self,
        *,
        resource: ModelRuntimeResource,
        payload: dict[str, Any],
        timeout_seconds: int,
        max_retries: int,
    ) -> dict[str, Any]:
        """使用统一模型重试参数请求 Rerank 服务。"""
        max_attempts = max_retries + 1
        last_error: Exception | None = None
        for attempt_index in range(max_attempts):
            try:
                response = await self._client.post(
                    self._build_endpoint(resource.base_url),
                    json=payload,
                    headers=self._build_headers(resource.api_key),
                    timeout=timeout_seconds,
                )
                response.raise_for_status()
                response_data = response.json()
                if not isinstance(response_data, dict):
                    raise ValueError("Rerank model response must be object")
                return response_data
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
                if not self._should_retry(exc) or attempt_index >= max_attempts - 1:
                    raise RetrievalDependencyError(
                        f"Rerank model request failed: {exc}"
                    ) from exc
                await asyncio.sleep(min(0.5 * (attempt_index + 1), 3.0))

        raise RetrievalDependencyError("Rerank model request failed") from last_error

    @staticmethod
    def _build_endpoint(base_url: str) -> str:
        """兼容模型地址填写到服务根路径或完整 /rerank 的形式。"""
        clean_url = base_url.rstrip("/")
        return clean_url if clean_url.endswith("/rerank") else f"{clean_url}/rerank"

    @staticmethod
    def _should_retry(exc: Exception) -> bool:
        """判断 Rerank 请求异常是否适合重试。"""
        if isinstance(exc, httpx.HTTPStatusError):
            return exc.response.status_code in MODEL_RETRYABLE_STATUS_CODES
        return isinstance(
            exc,
            (
                httpx.ConnectError,
                httpx.ConnectTimeout,
                httpx.ReadTimeout,
                httpx.PoolTimeout,
                httpx.RemoteProtocolError,
                httpx.NetworkError,
            ),
        )

    @staticmethod
    def _parse_response(
        *,
        response_data: dict[str, Any],
        document_count: int,
    ) -> list[int]:
        """校验 Rerank 响应并提取合法候选下标。"""
        results = response_data.get("results")
        if not isinstance(results, list):
            raise RetrievalDependencyError("Rerank model response missing results")

        ordered_indices: list[int] = []
        seen_indices: set[int] = set()
        for item in results:
            index = item.get("index") if isinstance(item, dict) else None
            if not isinstance(index, int):
                continue
            if index < 0 or index >= document_count or index in seen_indices:
                continue
            ordered_indices.append(index)
            seen_indices.add(index)

        if not ordered_indices:
            raise RetrievalDependencyError("Rerank model response has no valid index")

        for index in range(document_count):
            if index not in seen_indices:
                ordered_indices.append(index)
        return ordered_indices

    @staticmethod
    def _build_headers(api_key: str | None) -> dict[str, str]:
        """使用模型配置中的 API Key 构造鉴权请求头。"""
        return {"Authorization": f"Bearer {api_key}"} if api_key else {}


rerank_client = RerankClient()
