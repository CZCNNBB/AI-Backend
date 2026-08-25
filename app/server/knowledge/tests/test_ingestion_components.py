"""知识入库组件的无外部依赖单元测试。"""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from pydantic import ValidationError

from app.server.agent.src.model.resource import ModelRuntimeResource
from app.server.knowledge.src.embedding.service import EmbeddingService
from app.server.knowledge.src.ingestion.executor import ingestion_executor
from app.server.knowledge.src.models import IngestionRun
from app.server.knowledge.src.repositories import KnowledgeChunkRepository
from app.server.knowledge.src.schemas.knowledge_schemas import (
    KnowledgeBaseUpdateRequest,
    KnowledgeDocumentSubmitRequest,
)
from app.server.knowledge.src.services.knowledge_management_service import knowledge_management_service
from app.server.knowledge.src.split.schemas import (
    MarkdownDocumentHeaderThenRecursiveStrategyConfig,
    SplitMethodConfig,
)


class IngestionComponentTestCase(unittest.TestCase):
    """验证入库流程中稳定 ID、上下文和 Collection 命名。"""

    def test_chunk_id_is_stable_and_versioned(self) -> None:
        """相同输入应生成相同 ID，索引版本变化后 ID 必须变化。"""
        first = ingestion_executor._build_chunk_id(
            knowledge_id="kb_test",
            file_id="file_test",
            index_version=1,
            chunk_index=0,
        )
        repeated = ingestion_executor._build_chunk_id(
            knowledge_id="kb_test",
            file_id="file_test",
            index_version=1,
            chunk_index=0,
        )
        rebuilt = ingestion_executor._build_chunk_id(
            knowledge_id="kb_test",
            file_id="file_test",
            index_version=2,
            chunk_index=0,
        )

        self.assertEqual(first, repeated)
        self.assertNotEqual(first, rebuilt)
        self.assertLessEqual(len(first), 100)

    def test_context_uses_header_order(self) -> None:
        """标题元数据应转换为便于引用展示的层级路径。"""
        context = ingestion_executor._build_context(
            {"headers": {"h1": "第一章", "h2": "第二节"}}
        )

        self.assertEqual(context, "第一章 > 第二节")

    def test_collection_name_only_contains_safe_characters(self) -> None:
        """Collection 名称应清理 Milvus 不接受的特殊字符。"""
        name = knowledge_management_service._build_collection_name("kb-test/value")

        self.assertEqual(name, "knowledge_kb_test_value")

    def test_document_submit_inherits_knowledge_split_config(self) -> None:
        """文档没有指定切片方式时应复制知识库默认配置。"""
        request = KnowledgeDocumentSubmitRequest(knowledge_id="kb_test", file_id="file_test")
        knowledge_default = {
            "type": "recursive_character",
            "chunk_size": 800,
            "chunk_overlap": 100,
        }

        resolved = knowledge_management_service._resolve_document_split_config(
            request,
            knowledge_default,
        )

        self.assertEqual(resolved, knowledge_default)
        self.assertIsNot(resolved, knowledge_default)

    def test_document_submit_can_override_with_split_strategy(self) -> None:
        """文档提交时应允许使用组合切片策略覆盖知识库默认配置。"""
        request = KnowledgeDocumentSubmitRequest(
            knowledge_id="kb_test",
            file_id="file_test",
            split_strategy=MarkdownDocumentHeaderThenRecursiveStrategyConfig(
                type="markdown_document_header_then_recursive",
                chunk_size=1200,
                chunk_overlap=150,
            ),
        )

        resolved = knowledge_management_service._resolve_document_split_config(
            request,
            {"type": "recursive_character", "chunk_size": 800, "chunk_overlap": 100},
        )

        self.assertEqual(resolved["type"], "markdown_document_header_then_recursive")
        self.assertEqual(resolved["chunk_size"], 1200)
        self.assertEqual(resolved["chunk_overlap"], 150)

    def test_document_submit_rejects_two_split_selections(self) -> None:
        """单一切片方式和组合切片策略不能在同次提交中同时出现。"""
        with self.assertRaises(ValidationError):
            KnowledgeDocumentSubmitRequest(
                knowledge_id="kb_test",
                file_id="file_test",
                split_method=SplitMethodConfig(type="recursive_character"),
                split_strategy=MarkdownDocumentHeaderThenRecursiveStrategyConfig(
                    type="markdown_document_header_then_recursive"
                ),
            )

    def test_embedding_batch_response_restores_input_order(self) -> None:
        """批量响应即使乱序，也必须按 index 恢复为输入文本顺序。"""
        vectors = EmbeddingService._parse_embedding_response(
            {
                "data": [
                    {"index": 1, "embedding": [0.2, 0.3]},
                    {"index": 0, "embedding": [0.0, 0.1]},
                ]
            },
            expected_count=2,
            expected_dimension=2,
        )

        self.assertEqual(vectors, [[0.0, 0.1], [0.2, 0.3]])

    def test_embedding_batch_response_rejects_missing_vector(self) -> None:
        """批量响应数量少于输入文本时必须立即失败，不能产生错误映射。"""
        with self.assertRaisesRegex(ValueError, "数量不匹配"):
            EmbeddingService._parse_embedding_response(
                {"data": [{"index": 0, "embedding": [0.0, 0.1]}]},
                expected_count=2,
                expected_dimension=2,
            )

    def test_knowledge_update_accepts_explicit_null_description(self) -> None:
        """知识库更新应允许显式传 null 清空描述。"""
        request = KnowledgeBaseUpdateRequest(
            knowledge_id="kb_test",
            description=None,
        )

        self.assertIn("description", request.model_fields_set)

    def test_knowledge_update_rejects_empty_changes(self) -> None:
        """只传 knowledge_id 时应拒绝无意义更新。"""
        with self.assertRaises(ValidationError):
            KnowledgeBaseUpdateRequest(knowledge_id="kb_test")

    def test_replace_chunks_does_not_commit_business_transaction(self) -> None:
        """替换分块只能刷新 SQL，最终事务必须由入库执行器统一提交。"""
        db = MagicMock()
        repository = KnowledgeChunkRepository()

        repository.replace_document_chunks(db, document_id=1, chunks=[])

        db.exec.assert_called_once()
        db.add_all.assert_called_once_with([])
        db.flush.assert_called_once_with()
        db.commit.assert_not_called()


class IngestionExecutorLifecycleTestCase(unittest.IsolatedAsyncioTestCase):
    """验证入库执行器对不同生命周期任务的分发。"""

    async def test_delete_operation_only_runs_delete_pipeline(self) -> None:
        """delete 任务应等待专用删除流程完成，不得进入普通入库流程。"""
        run = IngestionRun(
            run_id="run_delete",
            document_id=1,
            knowledge_id="kb_test",
            file_id="file_test",
            operation="delete",
        )
        with patch.object(
            ingestion_executor,
            "_execute_delete",
            new=AsyncMock(),
        ) as execute_delete:
            await ingestion_executor.execute(run)

        execute_delete.assert_awaited_once_with(run)


class EmbeddingBatchServiceTestCase(unittest.IsolatedAsyncioTestCase):
    """验证 Embedding 批量请求从 HTTP 入参到响应排序的完整行为。"""

    async def test_embed_texts_sends_one_batch_request(self) -> None:
        """多条文本应进入同一个 input 数组，并按响应 index 恢复顺序。"""
        service = EmbeddingService()
        resource = ModelRuntimeResource(
            model_code="embedding-test",
            model_name="provider-embedding",
            model_type="embedding",
            base_url="http://127.0.0.1:8000/v1",
            api_key=None,
            extra_config={"dimension": 2, "batch_size": 32},
        )
        response = MagicMock()
        response.json.return_value = {
            "data": [
                {"index": 1, "embedding": [0.2, 0.3]},
                {"index": 0, "embedding": [0.0, 0.1]},
            ]
        }

        try:
            with patch.object(
                service,
                "_post_embedding_with_retry",
                new=AsyncMock(return_value=response),
            ) as post_embedding:
                vectors = await service.embed_texts(
                    texts=["first", "second"],
                    model_code="embedding-test",
                    resource=resource,
                )
        finally:
            await service.close()

        self.assertEqual(vectors, [[0.0, 0.1], [0.2, 0.3]])
        payload = post_embedding.await_args.kwargs["payload"]
        self.assertEqual(payload["input"], ["first", "second"])
        self.assertEqual(post_embedding.await_count, 1)


if __name__ == "__main__":
    unittest.main()
