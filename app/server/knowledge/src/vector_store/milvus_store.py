"""知识库向量写入使用的 MilvusClient 适配器。"""

import asyncio
import json
import os
from typing import Any

from pymilvus import DataType, MilvusClient

from app.server.knowledge.src.config import knowledge_config as settings
from app.server.knowledge.src.embedding.schemas import PersistentOptions, PersistentVectorWrite
from app.server.knowledge.src.logging_config import logger
from app.server.knowledge.src.milvus_client import milvus_client_manager


class MilvusVectorStoreService:
    """负责创建 Collection，并将知识切片及其向量写入 Milvus。"""

    REQUIRED_FIELDS = {
        "id", "content", "source", "chunk_id", "file_id",
        "chunk_index", "metadata", "embedding",
    }

    def __init__(self) -> None:
        """初始化连接锁和 Collection 创建锁。"""
        self._connection_lock = asyncio.Lock()
        # Collection 创建是低频操作，锁可避免同一进程并发创建同名集合。
        self._collection_lock = asyncio.Lock()

    async def close(self) -> None:
        """关闭知识库模块共享的 MilvusClient。"""
        await asyncio.to_thread(milvus_client_manager.close)

    async def health_check(self) -> str:
        """检查 Milvus 连接和目标数据库是否可用。"""
        await self._ensure_connection()
        return settings.milvus_database

    async def create_collection(self, *, collection_name: str, model_name: str, dimension: int) -> None:
        """显式创建知识库对应的 Milvus Collection。"""
        await self._ensure_connection()
        async with self._collection_lock:
            await asyncio.wait_for(
                asyncio.to_thread(
                    self._create_collection_if_missing_sync,
                    collection_name,
                    model_name,
                    dimension,
                ),
                timeout=settings.milvus_write_timeout,
            )

    async def ensure_collection_exists(self, collection_name: str) -> None:
        """校验 Collection 已存在，不存在时抛出明确错误。"""
        await self._ensure_connection()
        if not await asyncio.to_thread(self._has_collection_sync, collection_name):
            raise ValueError(f"Milvus collection not found: {collection_name}")

    async def drop_collection(self, collection_name: str) -> bool:
        """删除 Collection；不存在时返回 False，保证操作幂等。"""
        await self._ensure_connection()
        return await asyncio.to_thread(self._drop_collection_sync, collection_name)

    async def delete_file_vectors(self, collection_name: str, file_id: str) -> None:
        """删除指定文件的全部向量，供重试和重建前清理脏数据。"""
        await self._ensure_connection()
        await self.ensure_collection_exists(collection_name)
        await asyncio.wait_for(
            asyncio.to_thread(self._delete_file_vectors_sync, collection_name, file_id),
            timeout=settings.milvus_write_timeout,
        )

    async def delete_file_vectors_if_exists(self, collection_name: str, file_id: str) -> bool:
        """幂等删除文件向量；Collection 已不存在时直接返回 False。"""
        await self._ensure_connection()
        if not await asyncio.to_thread(self._has_collection_sync, collection_name):
            return False
        await asyncio.wait_for(
            asyncio.to_thread(self._delete_file_vectors_sync, collection_name, file_id),
            timeout=settings.milvus_write_timeout,
        )
        return True

    async def flush_collection(self, collection_name: str) -> None:
        """刷新 Collection，使本批写入在任务完成前稳定可见。"""
        await self._ensure_connection()
        await self.ensure_collection_exists(collection_name)
        await asyncio.wait_for(
            asyncio.to_thread(
                self._client().flush,
                collection_name=collection_name,
                timeout=settings.milvus_write_timeout,
            ),
            timeout=settings.milvus_write_timeout,
        )

    async def insert(
        self,
        text: str,
        embedding: list[float],
        options: PersistentOptions,
        model_name: str,
        expected_dimension: int,
    ) -> str:
        """校验并写入单条知识切片，保留对单条调用场景的兼容。"""
        del model_name  # Collection 已在创建时记录模型，写入阶段无需重复使用。
        await self.insert_many(
            writes=[PersistentVectorWrite(text=text, embedding=embedding, record=options)],
            expected_dimension=expected_dimension,
        )
        return options.chunk_id

    async def insert_many(
        self,
        writes: list[PersistentVectorWrite],
        expected_dimension: int,
    ) -> list[str]:
        """一次校验并写入同一 Collection 的多条知识切片。"""
        if not writes:
            return []
        collection_names = {write.record.collection_name for write in writes}
        if len(collection_names) != 1:
            raise ValueError("Milvus 批量写入只能包含同一个 Collection 的记录")
        for write in writes:
            self._validate_record(
                text=write.text,
                embedding=write.embedding,
                options=write.record,
                expected_dimension=expected_dimension,
            )

        collection_name = writes[0].record.collection_name
        await self._ensure_connection()
        await self.ensure_collection_exists(collection_name)
        try:
            await asyncio.wait_for(
                asyncio.to_thread(
                    self._insert_many_sync,
                    collection_name,
                    writes,
                    expected_dimension,
                ),
                timeout=settings.milvus_write_timeout,
            )
        except TimeoutError as exc:
            raise TimeoutError(
                f"Milvus batch insert timeout after {settings.milvus_write_timeout}s"
            ) from exc
        return [write.record.chunk_id for write in writes]

    async def _ensure_connection(self) -> None:
        """在线程池中按需初始化共享 MilvusClient。"""
        async with self._connection_lock:
            await asyncio.wait_for(
                asyncio.to_thread(milvus_client_manager.get_client),
                timeout=settings.milvus_connect_timeout,
            )

    @staticmethod
    def _client() -> MilvusClient:
        """获取已初始化或按需创建的共享客户端。"""
        return milvus_client_manager.get_client()

    def _has_collection_sync(self, collection_name: str) -> bool:
        """同步检查 Collection 是否存在。"""
        return bool(self._client().has_collection(
            collection_name=collection_name,
            timeout=settings.milvus_connect_timeout,
        ))

    def _drop_collection_sync(self, collection_name: str) -> bool:
        """同步删除 Collection。"""
        client = self._client()
        if not client.has_collection(collection_name=collection_name, timeout=settings.milvus_connect_timeout):
            return False
        client.drop_collection(collection_name=collection_name, timeout=settings.milvus_write_timeout)
        logger.info("Milvus Collection 删除完成: collection=%s", collection_name)
        return True

    def _insert_many_sync(
        self,
        collection_name: str,
        writes: list[PersistentVectorWrite],
        expected_dimension: int,
    ) -> None:
        """校验一次 Collection Schema，并批量写入多条行式数据。"""
        client = self._client()
        description = client.describe_collection(
            collection_name=collection_name,
            timeout=settings.milvus_query_timeout,
        )
        self._validate_collection_schema(description, expected_dimension)

        rows: list[dict[str, Any]] = []
        for write in writes:
            options = write.record
            # 文件名进入 metadata，便于标题检索区分同标题的不同文档。
            metadata = dict(options.metadata or {})
            if options.source and "file_name" not in metadata:
                metadata["file_name"] = os.path.splitext(options.source)[0]
            rows.append({
                "id": options.chunk_id,
                "content": write.text,
                "source": options.source,
                "chunk_id": options.chunk_id,
                "file_id": options.file_id,
                "chunk_index": options.chunk_index,
                "metadata": metadata,
                "embedding": write.embedding,
            })

        client.insert(
            collection_name=collection_name,
            data=rows,
            timeout=settings.milvus_write_timeout,
        )

    def _delete_file_vectors_sync(self, collection_name: str, file_id: str) -> None:
        """同步删除指定文件向量，并安全编码过滤表达式。"""
        client = self._client()
        # Milvus 3.0 在执行标量过滤删除前要求 Collection 已加载。
        client.load_collection(collection_name=collection_name, timeout=settings.milvus_write_timeout)
        client.delete(
            collection_name=collection_name,
            filter=f"file_id == {json.dumps(file_id, ensure_ascii=False)}",
            timeout=settings.milvus_write_timeout,
        )
        # 删除用于重试和回滚，返回前必须保证旧向量已不可见。
        client.flush(
            collection_name=collection_name,
            timeout=settings.milvus_write_timeout,
        )

    def _create_collection_if_missing_sync(
        self, collection_name: str, model_name: str, dimension: int
    ) -> None:
        """使用 MilvusClient Schema API 创建全新的知识库 Collection。"""
        client = self._client()
        if client.has_collection(collection_name=collection_name, timeout=settings.milvus_connect_timeout):
            return

        schema = MilvusClient.create_schema(
            auto_id=False,
            enable_dynamic_field=False,
            description=f"Embedding collection {collection_name} using {model_name}",
        )
        schema.add_field("id", DataType.VARCHAR, max_length=100, is_primary=True)
        schema.add_field(
            "content", DataType.VARCHAR, max_length=65535,
            enable_analyzer=True, enable_match=True,
        )
        schema.add_field("source", DataType.VARCHAR, max_length=500)
        schema.add_field("chunk_id", DataType.VARCHAR, max_length=100)
        schema.add_field("file_id", DataType.VARCHAR, max_length=100)
        schema.add_field("chunk_index", DataType.INT64)
        schema.add_field("metadata", DataType.JSON)
        schema.add_field("embedding", DataType.FLOAT_VECTOR, dim=dimension)

        # 创建 Collection 时一次提交全部索引，避免未完成索引的中间状态。
        index_params = MilvusClient.prepare_index_params()
        index_params.add_index(
            "embedding", index_type="IVF_FLAT", index_name="embedding_index",
            metric_type="COSINE", params={"nlist": 1024},
        )
        index_params.add_index("content", index_type="INVERTED", index_name="content_inverted_index")
        index_params.add_index("file_id", index_type="INVERTED", index_name="file_id_index")
        try:
            client.create_collection(
                collection_name=collection_name,
                schema=schema,
                index_params=index_params,
                timeout=settings.milvus_write_timeout,
            )
        except Exception:
            # 多进程部署时进程内锁无法覆盖其他进程；已创建则直接复用。
            if client.has_collection(collection_name=collection_name, timeout=settings.milvus_connect_timeout):
                return
            raise
        logger.info("Milvus Collection 创建完成: collection=%s dimension=%s", collection_name, dimension)

    @staticmethod
    def _validate_record(
        *, text: str, embedding: list[float],
        options: PersistentOptions, expected_dimension: int,
    ) -> None:
        """在访问 Milvus 前校验字段长度和向量维度。"""
        if len(options.chunk_id) > 100:
            raise ValueError("chunk_id length cannot exceed 100")
        if len(options.file_id) > 100:
            raise ValueError("file_id length cannot exceed 100")
        if len(options.source) > 500:
            raise ValueError("source length cannot exceed 500")
        if len(text) > 65535:
            raise ValueError("text length cannot exceed Milvus content limit 65535")
        if len(embedding) != expected_dimension:
            raise ValueError(
                f"embedding dimension mismatch: expected {expected_dimension}, got {len(embedding)}"
            )

    @classmethod
    def _validate_collection_schema(
        cls, description: dict[str, Any], vector_dimension: int
    ) -> None:
        """校验 Collection 字段和向量维度与固定 Schema 一致。"""
        fields = {
            field.get("name"): field
            for field in description.get("fields", [])
            if field.get("name")
        }
        missing_fields = cls.REQUIRED_FIELDS - set(fields)
        if missing_fields:
            raise ValueError(
                "Milvus collection schema mismatch, missing fields: "
                f"{sorted(missing_fields)}"
            )
        collection_dimension = int((fields["embedding"].get("params") or {}).get("dim") or 0)
        if not collection_dimension:
            raise ValueError("Milvus collection embedding dimension is unavailable")
        if collection_dimension != vector_dimension:
            raise ValueError(
                "Milvus collection embedding dimension mismatch: "
                f"collection={collection_dimension}, vector={vector_dimension}"
            )


# 模块级单例供任务执行器和应用生命周期复用。
vector_store_service = MilvusVectorStoreService()
