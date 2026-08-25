"""知识库统一服务门面。"""

import asyncio
from typing import Any

from app.common.db.postgres_db import check_postgres_health
from app.server.knowledge.src.config import knowledge_config
from app.server.knowledge.src.embedding.schemas import EmbeddingInput, EmbeddingOutput
from app.server.knowledge.src.embedding.service import embedding_service
from app.server.knowledge.src.ingestion.worker import ingestion_worker_manager
from app.server.knowledge.src.logging_config import logger
from app.server.knowledge.src.retrieval.milvus_store import milvus_store
from app.server.knowledge.src.retrieval.rerank_client import rerank_client
from app.server.knowledge.src.retrieval.retrieval_service import retrieval_service
from app.server.knowledge.src.retrieval.schemas import RetrievalInput, RetrievalOutput
from app.server.knowledge.src.split.schemas import SplitInput, SplitMethodConfig, SplitOutput
from app.server.knowledge.src.split.service import split_service
from app.server.knowledge.src.vector_store.milvus_store import vector_store_service


class KnowledgeService:
    """对外提供统一的知识库能力入口，并隐藏底层组件组织方式。"""

    def get_capabilities(self) -> dict[str, Any]:
        """返回当前知识库模块已经实现和暂未启用的能力。"""
        return {
            "split": {
                "enabled": True,
                "methods": ["markdown", "markdown_header", "recursive_character", "character", "qa_separator"],
                "strategies": ["markdown_document_header_then_recursive"],
            },
            "embedding": {"enabled": True, "config_source": "model_configs"},
            "retrieval": {
                "enabled": True,
                "modes": ["vector", "keyword", "hybrid", "document"],
                "rerank_configured": "per_request_model_code",
            },
            "ingestion": {
                "enabled": True,
                "worker_enabled": True,
                "queue": "postgresql_skip_locked",
            },
        }

    def split_text(self, request: SplitInput) -> SplitOutput:
        """使用指定方式或默认方式切分调用方直接提供的文本。"""
        if not request.text:
            raise ValueError("切片预览必须直接提供 text；file_id 将由后续入库流程统一处理")
        method = request.split_method or SplitMethodConfig(
            type=knowledge_config.split_default_method,
            chunk_size=knowledge_config.split_chunk_size,
            chunk_overlap=knowledge_config.split_chunk_overlap,
        )
        result = split_service.split(text=request.text, method=method, strategy=request.split_strategy)
        return SplitOutput(
            chunk_count=len(result["chunks"]),
            chunks=result["chunks"],
            split_method=result["split_method"],
            split_strategy=result["split_strategy"],
            effective_config=result["effective_config"],
        )

    async def embed_text(self, request: EmbeddingInput) -> EmbeddingOutput:
        """生成临时向量，不执行 Collection 创建或向量持久化。"""
        model_config = request.embedding_model_config
        if model_config is None:
            raise ValueError("向量预览必须提供 model_config.model_code 和 dimension")
        vector = await embedding_service.embed_text(
            request.text,
            model_code=model_config.model_code,
            extra_params=request.extra_params,
        )
        if len(vector) != model_config.dimension:
            raise ValueError(
                f"Embedding 向量维度不匹配: expected={model_config.dimension}, actual={len(vector)}"
            )
        return EmbeddingOutput(
            model_code=model_config.model_code,
            dimension=len(vector),
            embedding=vector,
        )

    async def retrieve(self, request: RetrievalInput) -> RetrievalOutput:
        """执行底层 Collection 检索；正式知识库 API 后续负责 kb_id 映射。"""
        return await retrieval_service.retrieve(request)

    async def readiness(self) -> dict[str, Any]:
        """真实检查知识库运行依赖，并返回可供接口展示的组件状态。"""
        checks: list[tuple[str, Any]] = [
            ("postgresql", asyncio.to_thread(check_postgres_health)),
            ("milvus_retrieval", milvus_store.health_check()),
            ("milvus_vector_store", vector_store_service.health_check()),
        ]
        results = await asyncio.gather(
            *(
                asyncio.wait_for(check, timeout=knowledge_config.startup_health_check_timeout)
                for _, check in checks
            ),
            return_exceptions=True,
        )

        components: dict[str, dict[str, str]] = {}
        for (name, _), result in zip(checks, results, strict=True):
            if isinstance(result, Exception):
                error_detail = str(result).strip() or result.__class__.__name__
                components[name] = {
                    "status": "failed",
                    "detail": error_detail,
                }
            else:
                components[name] = {
                    "status": "ok",
                    "detail": "ok" if result is None else str(result),
                }

        ready = all(component["status"] == "ok" for component in components.values())
        return {
            "status": "ready" if ready else "not_ready",
            "worker": "enabled",
            "components": components,
        }

    async def startup(self) -> None:
        """检查知识库全部基础依赖，并在检查通过后启动入库 Worker。"""
        split_service.health_check()
        logger.info("知识库本地切片能力检查通过")

        # 启动检查与 readiness 接口复用同一套逻辑，防止两处检查范围逐渐不一致。
        readiness = await self.readiness()
        for component_name, component in readiness["components"].items():
            if component["status"] == "ok":
                logger.info(
                    "知识库依赖检查通过: component=%s detail=%s",
                    component_name,
                    component["detail"],
                )
            else:
                logger.error(
                    "知识库依赖检查失败: component=%s reason=%s",
                    component_name,
                    component["detail"],
                )

        if readiness["status"] != "ready":
            failed_components = [
                name
                for name, component in readiness["components"].items()
                if component["status"] != "ok"
            ]
            raise RuntimeError(
                "知识库基础依赖健康检查失败: " + ", ".join(failed_components)
            )

        await ingestion_worker_manager.start()

    async def close(self) -> None:
        """关闭知识库模块持有的 HTTP 与 Milvus 连接。"""
        await ingestion_worker_manager.stop()
        await asyncio.gather(
            embedding_service.close(),
            rerank_client.close(),
            milvus_store.close(),
            vector_store_service.close(),
            return_exceptions=True,
        )


knowledge_service = KnowledgeService()

