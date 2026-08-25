from __future__ import annotations

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
from app.server.knowledge.src.logging_config import logger


class EmbeddingService:
    """通过 model_configs 中的 Embedding 模型配置生成向量。"""

    def __init__(self) -> None:
        """创建可复用连接池，模型连接信息在调用时按 model_code 解析。"""
        limits = httpx.Limits(
            max_keepalive_connections=settings.http_max_keepalive_connections,
            max_connections=settings.http_max_connections,
        )
        self._client = httpx.AsyncClient(limits=limits)

    async def close(self) -> None:
        """关闭底层 HTTP 连接池。"""
        await self._client.aclose()

    async def health_check(self, model_code: str) -> int:
        """调用指定 Embedding 模型并校验实际向量维度。"""
        resource = resolve_model_resource(model_code, "embedding")
        vector = await self.embed_text(
            text="embedding service health check",
            model_code=model_code,
        )
        actual_dimension = len(vector)
        if resource.dimension is None:
            raise ValueError(f"Embedding 模型 {model_code} 未配置向量维度")
        if actual_dimension != resource.dimension:
            raise ValueError(
                "embedding health check dimension mismatch: "
                f"expected {resource.dimension}, got {actual_dimension}"
            )
        return actual_dimension

    async def embed_text(
        self,
        text: str,
        model_code: str,
        extra_params: dict[str, Any] | None = None,
        resource: ModelRuntimeResource | None = None,
        timeout_seconds: int = DEFAULT_MODEL_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MODEL_MAX_RETRIES,
    ) -> list[float]:
        """使用知识库绑定的 Embedding model_code 生成单条文本向量。"""
        vectors = await self.embed_texts(
            texts=[text],
            model_code=model_code,
            extra_params=extra_params,
            resource=resource,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
        )
        return vectors[0]

    async def embed_texts(
        self,
        texts: list[str],
        model_code: str,
        extra_params: dict[str, Any] | None = None,
        resource: ModelRuntimeResource | None = None,
        timeout_seconds: int = DEFAULT_MODEL_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MODEL_MAX_RETRIES,
    ) -> list[list[float]]:
        """批量生成文本向量；调用方负责按模型批大小拆分超长输入列表。"""
        if not texts:
            return []
        clean_texts = [self._normalize_text(text) for text in texts]
        resolved_resource = resource or resolve_model_resource(model_code, "embedding")
        if resolved_resource.model_code != model_code:
            raise ValueError("Embedding model_code 与预解析模型资源不一致")
        if len(clean_texts) > resolved_resource.embedding_batch_size:
            raise ValueError(
                "单次 Embedding 文本数量超过模型批大小: "
                f"count={len(clean_texts)}, batch_size={resolved_resource.embedding_batch_size}"
            )

        payload: dict[str, Any] = {
            "model": resolved_resource.model_name,
            "input": clean_texts,
        }
        if extra_params:
            payload.update(extra_params)

        response = await self._post_embedding_with_retry(
            resource=resolved_resource,
            payload=payload,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
        )
        return self._parse_embedding_response(
            response.json(),
            expected_count=len(clean_texts),
            expected_dimension=resolved_resource.dimension,
        )

    async def _post_embedding_with_retry(
        self,
        *,
        resource: ModelRuntimeResource,
        payload: dict[str, Any],
        timeout_seconds: int,
        max_retries: int,
    ) -> httpx.Response:
        """调用 Embedding 接口，并使用统一模型参数处理重试。"""
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
                return response
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if not self._should_retry(exc) or attempt_index >= max_attempts - 1:
                    raise
                wait_seconds = min(0.5 * (attempt_index + 1), 3.0)
                logger.warning(
                    "Embedding 模型请求失败，准备重试：model_code=%s attempt=%s/%s wait=%.2fs reason=%s",
                    resource.model_code,
                    attempt_index + 1,
                    max_attempts,
                    wait_seconds,
                    exc,
                )
                await asyncio.sleep(wait_seconds)

        raise RuntimeError("embedding request failed without captured exception") from last_error

    @staticmethod
    def _build_endpoint(base_url: str) -> str:
        """兼容模型地址填写到 /v1 或完整 /embeddings 的形式。"""
        clean_url = base_url.rstrip("/")
        return clean_url if clean_url.endswith("/embeddings") else f"{clean_url}/embeddings"

    @staticmethod
    def _should_retry(exc: Exception) -> bool:
        """判断模型异常是否属于可重试的短暂故障。"""
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
    def _normalize_text(text: str) -> str:
        """校验并清理单条文本输入。"""
        if not isinstance(text, str):
            raise ValueError("text must be string")
        clean_text = text.strip()
        if not clean_text:
            raise ValueError("text cannot be empty")
        return clean_text

    @staticmethod
    def _build_headers(api_key: str | None) -> dict[str, str]:
        """使用模型配置中的 API Key 构造鉴权请求头。"""
        return {"Authorization": f"Bearer {api_key}"} if api_key else {}

    @staticmethod
    def _parse_embedding_response(
        data: dict[str, Any],
        *,
        expected_count: int,
        expected_dimension: int | None,
    ) -> list[list[float]]:
        """解析批量响应，并根据 index 恢复为与输入文本一致的向量顺序。"""
        items = data.get("data")
        if not isinstance(items, list) or len(items) != expected_count:
            raise ValueError(
                "Embedding 响应数量不匹配: "
                f"expected={expected_count}, actual={len(items) if isinstance(items, list) else 0}"
            )

        ordered_vectors: list[list[float] | None] = [None] * expected_count
        for fallback_index, item in enumerate(items):
            if not isinstance(item, dict):
                raise ValueError("Embedding 响应 data 的元素必须是对象")
            raw_index = item.get("index", fallback_index)
            if not isinstance(raw_index, int) or isinstance(raw_index, bool):
                raise ValueError("Embedding 响应 index 必须是整数")
            if raw_index < 0 or raw_index >= expected_count:
                raise ValueError(f"Embedding 响应 index 越界: {raw_index}")
            if ordered_vectors[raw_index] is not None:
                raise ValueError(f"Embedding 响应 index 重复: {raw_index}")

            embedding = item.get("embedding")
            if not isinstance(embedding, list):
                raise ValueError("Embedding 响应 embedding 必须是数组")
            vector = [float(value) for value in embedding]
            if expected_dimension is not None and len(vector) != expected_dimension:
                raise ValueError(
                    "Embedding 向量维度不匹配: "
                    f"expected={expected_dimension}, actual={len(vector)}, index={raw_index}"
                )
            ordered_vectors[raw_index] = vector

        if any(vector is None for vector in ordered_vectors):
            raise ValueError("Embedding 响应缺少部分输入对应的向量")
        return [vector for vector in ordered_vectors if vector is not None]


embedding_service = EmbeddingService()
