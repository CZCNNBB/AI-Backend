"""知识库统一服务测试。"""

import unittest
from unittest.mock import AsyncMock, patch

from app.server.knowledge.src.embedding.schemas import EmbeddingInput, EmbeddingModelConfig
from app.server.knowledge.src.services.knowledge_service import knowledge_service
from app.server.knowledge.src.split.schemas import (
    MarkdownDocumentHeaderThenRecursiveStrategyConfig,
    SplitInput,
)


class KnowledgeServiceTestCase(unittest.IsolatedAsyncioTestCase):
    """验证知识库统一门面的本地能力和向量化编排。"""

    def test_split_text_uses_default_method(self) -> None:
        """未指定切片参数时应使用统一配置中的默认方式。"""
        output = knowledge_service.split_text(SplitInput(text="第一段。\n\n第二段。"))

        self.assertGreaterEqual(output.chunk_count, 1)
        self.assertEqual(output.split_method, "recursive_character")
        self.assertIsNone(output.split_strategy)

    def test_split_text_supports_markdown_strategy(self) -> None:
        """Markdown 标题递归策略应保留实际策略名称和标题元数据。"""
        request = SplitInput(
            text="# 第一章\n正文内容",
            split_strategy=MarkdownDocumentHeaderThenRecursiveStrategyConfig(
                type="markdown_document_header_then_recursive",
                chunk_size=100,
                chunk_overlap=10,
            ),
        )

        output = knowledge_service.split_text(request)

        self.assertEqual(output.split_strategy, "markdown_document_header_then_recursive")
        self.assertEqual(output.chunks[0].metadata["headers"]["h1"], "第一章")

    async def test_embed_text_only_returns_temporary_vector(self) -> None:
        """临时向量化应校验维度并返回统一输出，不触发向量持久化。"""
        fake_vector = [0.1] * 3
        with patch(
            "app.server.knowledge.src.services.knowledge_service.embedding_service.embed_text",
            new=AsyncMock(return_value=fake_vector),
        ):
            output = await knowledge_service.embed_text(
                EmbeddingInput(
                    text="测试文本",
                    model_config=EmbeddingModelConfig(
                        model_code="embedding-test",
                        dimension=3,
                    ),
                )
            )

        self.assertEqual(output.model_code, "embedding-test")
        self.assertEqual(output.dimension, 3)
        self.assertEqual(output.embedding, fake_vector)

    def test_capabilities_exposes_postgres_ingestion_queue(self) -> None:
        """能力清单应暴露 PostgreSQL 抢占式入库队列。"""
        capabilities = knowledge_service.get_capabilities()

        self.assertTrue(capabilities["ingestion"]["enabled"])
        self.assertEqual(capabilities["ingestion"]["queue"], "postgresql_skip_locked")

    async def test_readiness_reports_dependency_timeout_type(self) -> None:
        """依赖异常没有文本时，readiness 仍应返回可定位的异常类型。"""
        with (
            patch(
                "app.server.knowledge.src.services.knowledge_service.check_postgres_health",
            ),
            patch(
                "app.server.knowledge.src.services.knowledge_service.embedding_service.health_check",
                new=AsyncMock(return_value=1024),
            ),
            patch(
                "app.server.knowledge.src.services.knowledge_service.milvus_store.health_check",
                new=AsyncMock(return_value="career_ai"),
            ),
            patch(
                "app.server.knowledge.src.services.knowledge_service.vector_store_service.health_check",
                new=AsyncMock(side_effect=TimeoutError()),
            ),
            patch(
                "app.server.knowledge.src.services.knowledge_service.rerank_client.health_check",
                new=AsyncMock(return_value=2),
            ),
        ):
            result = await knowledge_service.readiness()

        self.assertEqual(result["status"], "not_ready")
        self.assertEqual(result["components"]["milvus_vector_store"]["status"], "failed")
        self.assertEqual(result["components"]["milvus_vector_store"]["detail"], "TimeoutError")


    async def test_startup_starts_worker_after_dependencies_are_ready(self) -> None:
        """全部基础依赖健康时应启动知识入库 Worker。"""
        readiness = {
            "status": "ready",
            "worker": "enabled",
            "components": {
                "postgresql": {"status": "ok", "detail": "ok"},
                "milvus_retrieval": {"status": "ok", "detail": "career_ai"},
                "milvus_vector_store": {"status": "ok", "detail": "career_ai"},
            },
        }
        with (
            patch.object(knowledge_service, "readiness", new=AsyncMock(return_value=readiness)),
            patch(
                "app.server.knowledge.src.services.knowledge_service.ingestion_worker_manager.start",
                new=AsyncMock(),
            ) as start_worker,
        ):
            await knowledge_service.startup()

        start_worker.assert_awaited_once()

    async def test_startup_rejects_unhealthy_dependency(self) -> None:
        """任一基础依赖失败时应终止启动且不能启动入库 Worker。"""
        readiness = {
            "status": "not_ready",
            "worker": "enabled",
            "components": {
                "postgresql": {"status": "ok", "detail": "ok"},
                "milvus_retrieval": {"status": "failed", "detail": "connection refused"},
                "milvus_vector_store": {"status": "ok", "detail": "career_ai"},
            },
        }
        with (
            patch.object(knowledge_service, "readiness", new=AsyncMock(return_value=readiness)),
            patch(
                "app.server.knowledge.src.services.knowledge_service.ingestion_worker_manager.start",
                new=AsyncMock(),
            ) as start_worker,
        ):
            with self.assertRaisesRegex(RuntimeError, "milvus_retrieval"):
                await knowledge_service.startup()

        start_worker.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()

