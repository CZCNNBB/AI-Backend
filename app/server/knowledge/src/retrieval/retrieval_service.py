"""Retrieval 原子能力统一业务服务。"""

import asyncio
import re

from app.common.db.postgres_db import get_db_session
from app.server.knowledge.src.repositories import KnowledgeBaseRepository
from app.server.knowledge.src.config import knowledge_config as settings
from app.server.knowledge.src.retrieval.schemas import (
    EmbeddingConfig,
    EnhanceConfig,
    FilterConfig,
    RerankConfig,
    RetrievalConfig,
    RetrievalChunk,
    RetrievalDocument,
    RetrievalInput,
    RetrievalOutput,
)
from app.server.knowledge.src.embedding.service import embedding_service
from app.server.knowledge.src.retrieval.exceptions import RetrievalDependencyError, RetrievalValidationError
from app.server.knowledge.src.retrieval.milvus_store import milvus_store
from app.server.knowledge.src.retrieval.rerank_client import rerank_client
from app.server.knowledge.src.logging_config import logger


class RetrievalService:
    """根据 mode 编排单 Collection 或多 Collection 的向量、关键词、混合检索与可选 Rerank。"""

    async def retrieve(self, retrieval_input: RetrievalInput) -> RetrievalOutput:
        """根据输入配置执行当前已支持的 Chunk 检索链路。"""
        retrieval_config = retrieval_input.retrieval_config or self._default_config()
        filter_config = retrieval_input.filter_config or FilterConfig()
        rerank_config = retrieval_input.rerank_config or RerankConfig()
        enhance_config = retrieval_input.enhance_config or EnhanceConfig()

        if retrieval_config.mode == "document":
            # Document 模式只负责定位文档并拼接原文，不做压缩、不调用 LLM。
            return await self._retrieve_document(
                retrieval_input=retrieval_input,
                retrieval_config=retrieval_config,
                filter_config=filter_config,
                rerank_config=rerank_config,
                enhance_config=enhance_config,
            )

        if retrieval_config.mode == "keyword":
            # Keyword 模式不调用 Embedding，直接对 collection_list 中每个 Collection 并发执行 TEXT_MATCH。
            chunks = await self._keyword_search_collections(
                collection_list=retrieval_input.collection_list,
                query=retrieval_input.query,
                retrieval_config=retrieval_config,
                filter_config=filter_config,
            )
            if enhance_config.metadata_headers:
                # Metadata headers are an auxiliary recall route; they are fused only when enabled explicitly.
                metadata_chunks = await self._metadata_headers_search_collections(
                    collection_list=retrieval_input.collection_list,
                    query=retrieval_input.query,
                    retrieval_config=retrieval_config,
                    filter_config=filter_config,
                    enhance_config=enhance_config,
                )
                chunks = self._fuse_by_rrf(
                    vector_chunks=[],
                    keyword_chunks=chunks,
                    metadata_chunks=metadata_chunks,
                    rrf_k=retrieval_config.rrf_k,
                    top_k=retrieval_config.fetch_k * len(retrieval_input.collection_list),
                    hybrid_weights=retrieval_config.hybrid_weights,
                )
            chunks, rerank_used = await self._apply_optional_rerank(
                query=retrieval_input.query,
                chunks=chunks,
                rerank_config=rerank_config,
            )
            return self._build_output(
                mode="keyword",
                chunks=chunks,
                retrieval_config=retrieval_config,
                collection_list=retrieval_input.collection_list,
                rerank_used=rerank_used,
            )

        embedding_config = retrieval_input.embedding_config or self._resolve_embedding_config(
            retrieval_input.collection_list
        )
        # Vector 与 Hybrid 都只需要为同一个 query 生成一次查询向量，多 Collection 共享该向量。
        query_vector = await self._embed_query(
            query=retrieval_input.query,
            config=embedding_config,
        )

        if retrieval_config.mode == "hybrid":
            # Hybrid 对每个 Collection 同时做向量召回与关键词召回，任一路失败都向上抛出。
            vector_chunks, keyword_chunks = await asyncio.gather(
                self._vector_search_collections(
                    collection_list=retrieval_input.collection_list,
                    query_vector=query_vector,
                    retrieval_config=retrieval_config,
                    filter_config=filter_config,
                ),
                self._keyword_search_collections(
                    collection_list=retrieval_input.collection_list,
                    query=retrieval_input.query,
                    retrieval_config=retrieval_config,
                    filter_config=filter_config,
                ),
            )
            metadata_chunks = await self._metadata_headers_search_collections(
                collection_list=retrieval_input.collection_list,
                query=retrieval_input.query,
                retrieval_config=retrieval_config,
                filter_config=filter_config,
                enhance_config=enhance_config,
            )
            chunks = self._fuse_by_rrf(
                vector_chunks=vector_chunks,
                keyword_chunks=keyword_chunks,
                metadata_chunks=metadata_chunks,
                rrf_k=retrieval_config.rrf_k,
                top_k=retrieval_config.fetch_k * len(retrieval_input.collection_list),
                hybrid_weights=retrieval_config.hybrid_weights,
            )
            chunks, rerank_used = await self._apply_optional_rerank(
                query=retrieval_input.query,
                chunks=chunks,
                rerank_config=rerank_config,
            )
            return self._build_output(
                mode="hybrid",
                chunks=chunks,
                retrieval_config=retrieval_config,
                collection_list=retrieval_input.collection_list,
                rerank_used=rerank_used,
            )

        # Vector 模式对每个 Collection 并发执行向量召回，然后按 COSINE 分数做全局排序。
        chunks = await self._vector_search_collections(
            collection_list=retrieval_input.collection_list,
            query_vector=query_vector,
            retrieval_config=retrieval_config,
            filter_config=filter_config,
        )
        if enhance_config.metadata_headers:
            # Vector mode can still use metadata headers as an extra recall signal after query embedding is ready.
            metadata_chunks = await self._metadata_headers_search_collections(
                collection_list=retrieval_input.collection_list,
                query=retrieval_input.query,
                retrieval_config=retrieval_config,
                filter_config=filter_config,
                enhance_config=enhance_config,
            )
            chunks = self._fuse_by_rrf(
                vector_chunks=chunks,
                keyword_chunks=[],
                metadata_chunks=metadata_chunks,
                rrf_k=retrieval_config.rrf_k,
                top_k=retrieval_config.fetch_k * len(retrieval_input.collection_list),
                hybrid_weights=retrieval_config.hybrid_weights,
            )
        chunks, rerank_used = await self._apply_optional_rerank(
            query=retrieval_input.query,
            chunks=chunks,
            rerank_config=rerank_config,
        )
        return self._build_output(
            mode="vector",
            chunks=chunks,
            retrieval_config=retrieval_config,
            collection_list=retrieval_input.collection_list,
            rerank_used=rerank_used,
        )

    async def _embed_query(self, *, query: str, config: EmbeddingConfig) -> list[float]:
        """复用统一 EmbeddingService 生成查询向量并校验维度。"""
        try:
            vector = await embedding_service.embed_text(query, model_code=config.model_code)
        except Exception as exc:  # noqa: BLE001
            raise RetrievalDependencyError(f"Embedding 模型请求失败: {exc}") from exc
        if len(vector) != config.dimension:
            raise RetrievalValidationError(
                f"Embedding 向量维度不匹配: expected={config.dimension}, actual={len(vector)}"
            )
        return vector

    async def _retrieve_document(
        self,
        *,
        retrieval_input: RetrievalInput,
        retrieval_config: RetrievalConfig,
        filter_config: FilterConfig,
        rerank_config: RerankConfig,
        enhance_config: EnhanceConfig,
    ) -> RetrievalOutput:
        """执行全文召回：先定位最相关文档，再回查该文档全部 Chunk 并拼接原文。"""
        embedding_config = retrieval_input.embedding_config or self._resolve_embedding_config(
            retrieval_input.collection_list
        )
        # Document 模式第一步仍是召回候选 Chunk，用命中 Chunk 的 file_id 定位整篇文档。
        query_vector = await self._embed_query(
            query=retrieval_input.query,
            config=embedding_config,
        )
        candidate_chunks = await self._vector_search_collections(
            collection_list=retrieval_input.collection_list,
            query_vector=query_vector,
            retrieval_config=retrieval_config,
            filter_config=filter_config,
        )

        if enhance_config.metadata_headers:
            # 标题增强只参与“选中文档”阶段，不会把 metadata 返回给调用方。
            metadata_chunks = await self._metadata_headers_search_collections(
                collection_list=retrieval_input.collection_list,
                query=retrieval_input.query,
                retrieval_config=retrieval_config,
                filter_config=filter_config,
                enhance_config=enhance_config,
            )
            candidate_chunks = self._fuse_by_rrf(
                vector_chunks=candidate_chunks,
                keyword_chunks=[],
                metadata_chunks=metadata_chunks,
                rrf_k=retrieval_config.rrf_k,
                top_k=retrieval_config.fetch_k * len(retrieval_input.collection_list),
                hybrid_weights=retrieval_config.hybrid_weights,
            )

        candidate_chunks, rerank_used = await self._apply_optional_rerank(
            query=retrieval_input.query,
            chunks=candidate_chunks,
            rerank_config=rerank_config,
        )
        if not candidate_chunks:
            return RetrievalOutput(
                mode="document",
                result_count=0,
                rerank_used=rerank_used,
                results=[],
                document=None,
            )

        # 只取最终排序第一的候选 Chunk 作为目标文档，避免一次请求返回多篇全文导致输出过大。
        hit_chunk = candidate_chunks[0]
        document_chunks = await milvus_store.query_chunks_by_file(
            collection_name=hit_chunk.collection_name,
            file_id=hit_chunk.file_id,
            max_chunks=settings.document_max_chunks,
        )
        document = self._build_document_from_chunks(
            hit_chunk=hit_chunk,
            document_chunks=document_chunks,
        )
        return RetrievalOutput(
            mode="document",
            result_count=1 if document is not None else 0,
            rerank_used=rerank_used,
            results=[],
            document=document,
        )

    @classmethod
    def _build_document_from_chunks(
        cls,
        *,
        hit_chunk: RetrievalChunk,
        document_chunks: list[RetrievalChunk],
    ) -> RetrievalDocument | None:
        """将同一文档的 Chunk 按顺序拼接为原文，并移除相邻 Chunk 的重叠文本。"""
        if not document_chunks:
            return None

        merged_content = ""
        seen_chunk_ids: set[str] = set()
        effective_chunks: list[RetrievalChunk] = []
        for chunk in sorted(document_chunks, key=lambda item: item.chunk_index):
            if chunk.chunk_id in seen_chunk_ids:
                continue
            seen_chunk_ids.add(chunk.chunk_id)
            effective_chunks.append(chunk)
            merged_content = cls._append_without_overlap(merged_content, chunk.content)

        first_chunk = effective_chunks[0]
        return RetrievalDocument(
            collection_name=hit_chunk.collection_name,
            file_id=hit_chunk.file_id,
            source=hit_chunk.source or first_chunk.source,
            content=merged_content,
            char_count=len(merged_content),
            chunk_count=len(effective_chunks),
            score=hit_chunk.score,
            hit_chunk_id=hit_chunk.chunk_id,
        )

    @staticmethod
    def _append_without_overlap(existing_content: str, next_content: str) -> str:
        """追加下一个 Chunk 内容，并去掉与已拼接文本尾部完全重复的重叠部分。"""
        if not next_content:
            return existing_content
        if not existing_content:
            return next_content

        # 只检查相邻 Chunk 常见的重叠窗口，避免长文档拼接时做过大的字符串比较。
        max_overlap = min(len(existing_content), len(next_content), 500)
        for overlap_size in range(max_overlap, 0, -1):
            if existing_content[-overlap_size:] == next_content[:overlap_size]:
                return existing_content + next_content[overlap_size:]

        # 没有检测到重叠时，用换行连接相邻 Chunk，保证段落之间不会被硬粘在一起。
        separator = "" if existing_content.endswith("\n") or next_content.startswith("\n") else "\n"
        return existing_content + separator + next_content

    async def _vector_search_collections(
        self,
        *,
        collection_list: list[str],
        query_vector: list[float],
        retrieval_config: RetrievalConfig,
        filter_config: FilterConfig,
    ) -> list[RetrievalChunk]:
        """并发检索多个 Collection 的向量候选并按分数全局排序。"""
        tasks = [
            milvus_store.vector_search(
                collection_name=collection_name,
                query_vector=query_vector,
                fetch_k=retrieval_config.fetch_k,
                top_k=retrieval_config.fetch_k,
                similarity_threshold=retrieval_config.similarity_threshold,
                file_ids=filter_config.file_ids,
            )
            for collection_name in collection_list
        ]
        collection_results = await asyncio.gather(*tasks)
        chunks = [chunk for result in collection_results for chunk in result]
        return sorted(chunks, key=lambda chunk: chunk.score, reverse=True)

    async def _keyword_search_collections(
        self,
        *,
        collection_list: list[str],
        query: str,
        retrieval_config: RetrievalConfig,
        filter_config: FilterConfig,
    ) -> list[RetrievalChunk]:
        """并发执行多 Collection 关键词检索，并对候选结果进行全局排序。"""
        tasks = [
            milvus_store.keyword_search(
                collection_name=collection_name,
                query=query,
                fetch_k=retrieval_config.fetch_k,
                top_k=retrieval_config.fetch_k,
                file_ids=filter_config.file_ids,
            )
            for collection_name in collection_list
        ]
        collection_results = await asyncio.gather(*tasks)
        chunks = [chunk for result in collection_results for chunk in result]
        return sorted(chunks, key=lambda chunk: chunk.score, reverse=True)

    async def _metadata_headers_search_collections(
        self,
        *,
        collection_list: list[str],
        query: str,
        retrieval_config: RetrievalConfig,
        filter_config: FilterConfig,
        enhance_config: EnhanceConfig,
    ) -> list[RetrievalChunk]:
        """在所有目标 Collection 中执行可选的标题元数据召回。"""
        if not enhance_config.metadata_headers:
            return []

        # The scan limit is intentionally internal: callers only decide whether the enhancement is enabled.
        scan_limit = retrieval_config.fetch_k * 50
        tasks = [
            milvus_store.metadata_headers_search(
                collection_name=collection_name,
                query=query,
                fetch_k=retrieval_config.fetch_k,
                scan_limit=scan_limit,
                file_ids=filter_config.file_ids,
            )
            for collection_name in collection_list
        ]
        collection_results = await asyncio.gather(*tasks)
        chunks = [chunk for result in collection_results for chunk in result]
        return sorted(chunks, key=lambda chunk: chunk.score, reverse=True)

    @staticmethod
    def _build_headers_path(metadata: dict | None) -> str | None:
        """从 metadata.headers 按层级拼接标题路径，用于 Rerank 输入增强。"""
        if not isinstance(metadata, dict):
            return None
        headers = metadata.get("headers")
        if not isinstance(headers, dict):
            return None

        def _sort_key(key: str) -> tuple[int, str]:
            """生成标题层级排序键。"""
            key_lower = key.strip().lower()
            match = re.fullmatch(r"h(\d+)", key_lower)
            if match:
                return int(match.group(1)), key_lower
            return 10000, key_lower

        sorted_items = sorted(headers.items(), key=lambda item: _sort_key(str(item[0])))
        values = [str(value).strip() for _, value in sorted_items if str(value).strip()]
        return " > ".join(values) if values else None

    @staticmethod
    def _build_rerank_document(chunk: RetrievalChunk) -> str:
        """构造 Rerank 增强输入：来源文件 + 标题路径 + 正文。"""
        parts: list[str] = []
        metadata = chunk.metadata

        # 来源文件：优先用 chunk.source，其次 metadata.file_name
        source = chunk.source
        if not source and isinstance(metadata, dict):
            source = metadata.get("file_name", "")
        if source:
            parts.append(f"来源文件：{source}")

        # 标题路径：从 metadata.headers 按 h1 > h2 > h3 层级拼接
        headers_path = RetrievalService._build_headers_path(metadata)
        if headers_path:
            parts.append(f"标题路径：{headers_path}")

        # 正文
        parts.append(f"正文：\n{chunk.content}")
        return "\n".join(parts)

    async def _apply_optional_rerank(
        self,
        *,
        query: str,
        chunks: list[RetrievalChunk],
        rerank_config: RerankConfig,
    ) -> tuple[list[RetrievalChunk], bool]:
        """按配置对候选结果执行可选 Rerank，失败时默认保留原顺序。"""
        if not rerank_config.enable or len(chunks) <= 1:
            return chunks, False

        max_candidates = rerank_config.max_candidates
        max_chars = rerank_config.max_chars
        rerank_candidates = chunks[:max_candidates]
        remaining_chunks = chunks[max_candidates:]
        # 先拼接 source + headers + content，再整体截断；
        # source 和 headers 位于文本前部，截断时优先保留。
        documents = [
            self._build_rerank_document(chunk)[:max_chars]
            for chunk in rerank_candidates
        ]

        try:
            rerank_order = await rerank_client.rerank(
                query=query,
                documents=documents,
                config=rerank_config,
            )
        except RetrievalDependencyError as exc:
            # Rerank 是检索后的增强步骤，不应该因为增强失败导致主检索失败。
            # 因此这里固定降级为原始召回顺序，并通过 rerank_used=false 告诉调用方本次未使用重排结果。
            logger.warning("Rerank 调用失败，保留原始召回顺序：%s", exc)
            return chunks, False

        ranked_candidates = [rerank_candidates[index] for index in rerank_order]
        # Rerank 只处理前 max_candidates 条，未参与 Rerank 的候选按原顺序追加。
        return ranked_candidates + remaining_chunks, True

    def _build_output(
        self,
        *,
        mode: str,
        chunks: list[RetrievalChunk],
        retrieval_config: RetrievalConfig,
        collection_list: list[str],
        rerank_used: bool,
    ) -> RetrievalOutput:
        """按兜底策略截断候选并组装统一输出结构。"""
        final_chunks = self._select_final_results(
            chunks=chunks,
            retrieval_config=retrieval_config,
            collection_list=collection_list,
        )
        return RetrievalOutput(
            mode=mode,
            result_count=len(final_chunks),
            rerank_used=rerank_used,
            results=final_chunks,
        )

    def _select_final_results(
        self,
        *,
        chunks: list[RetrievalChunk],
        retrieval_config: RetrievalConfig,
        collection_list: list[str],
    ) -> list[RetrievalChunk]:
        """根据是否开启每库兜底保留，选择最终返回结果。"""
        if retrieval_config.per_collection_min_keep <= 0:
            # per_collection_min_keep 为 0 时不启用兜底，纯全局排序后截取 top_k。
            return chunks[: retrieval_config.top_k]

        return self._apply_per_collection_min_keep(
            chunks=chunks,
            collection_list=collection_list,
            min_keep=retrieval_config.per_collection_min_keep,
            top_k=retrieval_config.top_k,
        )

    @staticmethod
    def _apply_per_collection_min_keep(
        *,
        chunks: list[RetrievalChunk],
        collection_list: list[str],
        min_keep: int,
        top_k: int,
    ) -> list[RetrievalChunk]:
        """尽量保证每个 Collection 至少保留 min_keep 条结果，再按全局顺序补齐。"""
        if not chunks or top_k <= 0:
            return []

        selected_keys: set[tuple[str, str]] = set()
        must_keep: list[RetrievalChunk] = []

        for collection_name in collection_list:
            kept_for_collection = 0
            for chunk in chunks:
                chunk_key = (chunk.collection_name, chunk.chunk_id)
                if chunk.collection_name != collection_name or chunk_key in selected_keys:
                    continue
                # 每个 Collection 从全局排序后的候选里取本库最高分的若干条作为兜底候选。
                must_keep.append(chunk)
                selected_keys.add(chunk_key)
                kept_for_collection += 1
                if kept_for_collection >= min_keep:
                    break

        # 如果 top_k 小于可兜底的 Collection 数，只能保留全局分数更靠前的兜底结果。
        must_keep = sorted(must_keep, key=lambda chunk: chunk.score, reverse=True)[:top_k]
        selected_keys = {(chunk.collection_name, chunk.chunk_id) for chunk in must_keep}

        final_chunks = list(must_keep)
        for chunk in chunks:
            if len(final_chunks) >= top_k:
                break
            chunk_key = (chunk.collection_name, chunk.chunk_id)
            if chunk_key in selected_keys:
                continue
            final_chunks.append(chunk)
            selected_keys.add(chunk_key)

        # 最终仍然按分数排序返回，兜底只影响“是否进入结果集”，不打乱相关性顺序。
        return sorted(final_chunks, key=lambda chunk: chunk.score, reverse=True)

    @staticmethod
    def _fuse_by_rrf(
        *,
        vector_chunks: list[RetrievalChunk],
        keyword_chunks: list[RetrievalChunk],
        rrf_k: int,
        top_k: int,
        hybrid_weights: dict[str, float] | None = None,
        metadata_chunks: list[RetrievalChunk] | None = None,
        metadata_weight: float | None = None,
    ) -> list[RetrievalChunk]:
        """
        按 collection_name + chunk_id 去重并使用加权 RRF 融合两路排名。

        计算口径对齐当前主项目：rank 从 0 开始，同一 Chunk 在两路命中时累加分数。
        RRF 只使用排名，不直接混加 COSINE 与 Keyword 的原始分数；权重只影响两路排名贡献。
        """
        chunks_by_key: dict[tuple[str, str], RetrievalChunk] = {}
        rrf_scores: dict[tuple[str, str], float] = {}
        effective_metadata_weight = (
            settings.metadata_headers_weight
            if metadata_weight is None
            else metadata_weight
        )
        route_weights = {
            # hybrid_weights controls only the public vector/keyword routes.
            "vector": 1.0,
            "keyword": 1.0,
            **(hybrid_weights or {}),
            # metadata_headers is an internal auxiliary route controlled by service env config.
            "metadata_headers": effective_metadata_weight,
        }
        routes = [
            ("vector", vector_chunks),
            ("keyword", keyword_chunks),
        ]
        if metadata_chunks:
            routes.append(("metadata_headers", metadata_chunks))

        for route_name, ranked_chunks in routes:
            route_weight = route_weights[route_name]
            if route_weight <= 0:
                continue
            for rank, chunk in enumerate(ranked_chunks):
                chunk_key = (chunk.collection_name, chunk.chunk_id)
                # 多 Collection 下 chunk_id 可能重复，所以必须连同 collection_name 一起作为去重键。
                # 去重时优先保留带 metadata 的版本，避免 metadata_headers 路的上下文丢失。
                existing = chunks_by_key.get(chunk_key)
                if existing is None:
                    chunks_by_key[chunk_key] = chunk
                elif chunk.metadata and not existing.metadata:
                    chunks_by_key[chunk_key] = chunk
                # 每一路只按排名贡献 RRF 分数，再乘以该路权重，避免直接混合不同分数体系。
                rrf_scores[chunk_key] = (
                    rrf_scores.get(chunk_key, 0.0)
                    + route_weight / (rrf_k + rank)
                )

        sorted_chunk_keys = sorted(
            rrf_scores,
            key=lambda chunk_key: rrf_scores[chunk_key],
            reverse=True,
        )
        fused_chunks = [
            chunks_by_key[chunk_key].model_copy(
                update={"score": rrf_scores[chunk_key]}
            )
            for chunk_key in sorted_chunk_keys[:top_k]
        ]
        return fused_chunks

    @staticmethod
    def _resolve_embedding_config(collection_list: list[str]) -> EmbeddingConfig:
        """根据知识库 Collection 解析并校验统一的 Embedding 模型配置。"""
        repository = KnowledgeBaseRepository()
        with get_db_session() as db:
            records = repository.get_by_collection_names(db, collection_list)

        records_by_collection = {record.collection_name: record for record in records}
        missing_collections = [
            name for name in collection_list if name not in records_by_collection
        ]
        if missing_collections:
            raise RetrievalValidationError(
                "以下 Collection 未关联知识库：" + "、".join(missing_collections)
            )

        model_pairs = {
            (record.embedding_model, record.embedding_dimension)
            for record in records
        }
        if len(model_pairs) != 1:
            raise RetrievalValidationError(
                "多知识库联合向量检索要求使用相同的 Embedding 模型和向量维度"
            )

        model_code, dimension = next(iter(model_pairs))
        return EmbeddingConfig(model_code=model_code, dimension=dimension)

    @staticmethod
    def _default_config() -> RetrievalConfig:
        """使用 RetrievalConfig 自身定义的默认召回参数。"""
        return RetrievalConfig()


# 模块级单例供 Router 复用。
retrieval_service = RetrievalService()
