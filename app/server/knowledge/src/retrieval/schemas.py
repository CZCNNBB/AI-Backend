"""Retrieval 原子能力请求与响应模型。"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class RetrievalConfig(BaseModel):
    """单次检索使用的召回参数。"""

    mode: Literal["vector", "keyword", "hybrid", "document"] = Field(
        default="vector",
        description="当前支持 vector、keyword、hybrid 和 document 检索",
    )
    top_k: int = Field(default=10, ge=1, le=100, description="最终返回结果数量")
    fetch_k: int = Field(
        default=30,
        ge=1,
        le=200,
        description="每个 Collection 初始召回数量",
    )
    similarity_threshold: float = Field(
        default=0.2,
        ge=-1.0,
        le=1.0,
        description="COSINE 相似度下限",
    )
    metric_type: Literal["COSINE"] = Field(
        default="COSINE",
        description="当前只支持 COSINE 距离度量",
    )
    rrf_k: int = Field(
        default=60,
        ge=1,
        le=1000,
        description="Hybrid 模式的 RRF 排名平滑参数",
    )
    hybrid_weights: dict[Literal["vector", "keyword"], float] | None = Field(
        default=None,
        description=(
            "Hybrid 模式的可选权重配置；不传表示向量检索和关键词检索等权，"
            "支持 {\"vector\": 1.0, \"keyword\": 1.0}"
        ),
    )
    per_collection_min_keep: int = Field(
        default=0,
        ge=0,
        le=10,
        description="每个 Collection 的兜底保留数量；0 表示不开启兜底，非 0 表示开启",
    )

    @field_validator("hybrid_weights")
    @classmethod
    def validate_hybrid_weights(
        cls,
        hybrid_weights: dict[Literal["vector", "keyword"], float] | None,
    ) -> dict[Literal["vector", "keyword"], float] | None:
        """校验 Hybrid 权重只包含已支持的检索路由，并拒绝负数权重。"""
        if hybrid_weights is None:
            return None

        if not hybrid_weights:
            # 空 JSON 与不传语义一致，统一归一成 None，避免业务层处理两种空值。
            return None

        for route_name, route_weight in hybrid_weights.items():
            if route_weight < 0:
                raise ValueError(f"{route_name} weight cannot be negative")

        if all(route_weight == 0 for route_weight in hybrid_weights.values()):
            raise ValueError("hybrid_weights cannot make all routes weight zero")

        return hybrid_weights


class EmbeddingConfig(BaseModel):
    """检索查询向量使用的 Embedding 配置。"""

    model_code: str = Field(..., min_length=1, description="平台 Embedding 模型编码")
    dimension: int = Field(..., ge=1, description="预期向量维度")


class RerankConfig(BaseModel):
    """检索候选结果使用的 Rerank 配置。"""

    enable: bool = Field(default=False, description="是否启用 Rerank")
    model_code: str | None = Field(
        default=None,
        description="平台 Rerank 模型编码；启用 Rerank 时必须提供",
    )
    max_candidates: int = Field(
        default=30,
        ge=1,
        le=200,
        description="最多送入 Rerank 的候选数量；不传时使用服务默认配置",
    )
    max_chars: int = Field(
        default=1500,
        ge=100,
        le=10000,
        description="单条候选送入 Rerank 的最大字符数；不传时使用服务默认配置",
    )



class EnhanceConfig(BaseModel):
    """不改变公开响应结构的可选检索增强配置。"""

    metadata_headers: bool = Field(
        default=False,
        description="Enable auxiliary recall by matching query against metadata.headers",
    )


class FilterConfig(BaseModel):
    """检索允许使用的结构化过滤条件。"""

    file_ids: list[str] = Field(
        default_factory=list,
        max_length=1000,
        description="只在指定文件范围内检索；空列表表示不过滤",
    )

    @field_validator("file_ids")
    @classmethod
    def normalize_file_ids(cls, file_ids: list[str]) -> list[str]:
        """清理文件 ID、拒绝空值并按原顺序去重。"""
        normalized: list[str] = []
        seen: set[str] = set()
        for file_id in file_ids:
            clean_file_id = file_id.strip()
            if not clean_file_id:
                raise ValueError("file_ids cannot contain empty value")
            if len(clean_file_id) > 100:
                raise ValueError("file_id length cannot exceed 100")
            if clean_file_id not in seen:
                normalized.append(clean_file_id)
                seen.add(clean_file_id)
        return normalized


class RetrievalInput(BaseModel):
    """Retrieval 任务的自定义输入参数。"""

    collection_list: list[str] = Field(
        ...,
        min_length=1,
        max_length=20,
        description="目标 Milvus collection 列表；一个元素表示单库检索，多个元素表示多库检索",
    )
    query: str = Field(..., min_length=1, max_length=10000, description="用户查询文本")
    retrieval_config: RetrievalConfig | None = Field(
        default=None,
        description="单次检索配置；不传时使用服务默认配置",
    )
    embedding_config: EmbeddingConfig | None = Field(
        default=None,
        description="单次 Embedding 配置；不传时使用服务默认配置",
    )
    rerank_config: RerankConfig | None = Field(
        default=None,
        description="可选 Rerank 配置；不传时不启用 Rerank",
    )
    enhance_config: EnhanceConfig | None = Field(
        default=None,
        description="Optional retrieval enhancement switches; disabled by default",
    )
    filter_config: FilterConfig | None = Field(
        default=None,
        description="可选结构化过滤条件",
    )

    @field_validator("collection_list")
    @classmethod
    def normalize_collection_list(cls, collection_list: list[str]) -> list[str]:
        """清理 Collection 名称、拒绝非法名称并按原顺序去重。"""
        normalized: list[str] = []
        seen: set[str] = set()
        for collection_name in collection_list:
            clean_name = collection_name.strip()
            if not clean_name:
                raise ValueError("collection_list cannot contain empty value")
            if len(clean_name) > 255:
                raise ValueError("collection name length cannot exceed 255")
            if not clean_name[0].isascii() or (
                not clean_name[0].isalpha() and clean_name[0] != "_"
            ):
                raise ValueError(
                    "collection name must start with an ASCII letter or underscore"
                )
            if not all(
                char.isascii() and (char.isalnum() or char == "_")
                for char in clean_name
            ):
                raise ValueError(
                    "collection name can only contain ASCII letters, numbers and underscore"
                )
            if clean_name not in seen:
                normalized.append(clean_name)
                seen.add(clean_name)
        return normalized

    @field_validator("query")
    @classmethod
    def normalize_query(cls, query: str) -> str:
        """清理查询首尾空白并拒绝纯空白查询。"""
        clean_query = query.strip()
        if not clean_query:
            raise ValueError("query cannot be empty")
        return clean_query

    @model_validator(mode="after")
    def validate_total_result_limit(self) -> "RetrievalInput":
        """校验最终返回数量不能超过多 Collection 总候选上限。"""
        if self.retrieval_config is None:
            return self
        max_candidates = self.retrieval_config.fetch_k * len(self.collection_list)
        if self.retrieval_config.top_k > max_candidates:
            raise ValueError(
                "top_k must be less than or equal to fetch_k * collection count"
            )
        return self


class RetrievalResult(BaseModel):
    """检索返回的稳定结果结构。"""

    collection_name: str = Field(..., description="结果来源 Milvus collection 名称")
    chunk_id: str = Field(..., description="切片 ID")
    file_id: str = Field(..., description="文件 ID")
    source: str = Field(..., description="来源标识，通常为文件名")
    chunk_index: int = Field(..., ge=0, description="切片在文档中的顺序")
    content: str = Field(..., description="切片正文")
    score: float = Field(
        ...,
        description="Vector 为 COSINE 相似度；Keyword 为排名分数；Hybrid 为 RRF 分数",
    )
    metadata: dict | None = Field(
        default=None,
        exclude=True,
        description="内部使用的 Milvus metadata，不对外返回",
    )


# 兼容服务内部既有命名：当前检索结果仍然是 Chunk 粒度。
RetrievalChunk = RetrievalResult


class RetrievalDocument(BaseModel):
    """全文召回模式返回的文档原文结构。"""

    collection_name: str = Field(..., description="文档来源 Milvus collection 名称")
    file_id: str = Field(..., description="文件 ID")
    source: str = Field(..., description="来源标识，通常为文件名")
    content: str = Field(..., description="按 chunk_index 拼接并去重后的文档原文")
    char_count: int = Field(..., ge=0, description="文档原文字符数")
    chunk_count: int = Field(..., ge=0, description="参与拼接的 chunk 数量")
    score: float = Field(..., description="定位该文档时命中的候选 chunk 分数")
    hit_chunk_id: str = Field(..., description="用于定位该文档的命中 chunk ID")


class RetrievalOutput(BaseModel):
    """当前 Chunk 检索模式的输出参数。"""

    mode: Literal["vector", "keyword", "hybrid", "document"] = Field(
        ...,
        description="实际执行的检索模式",
    )
    result_count: int = Field(..., ge=0, description="返回结果数量")
    rerank_used: bool = Field(default=False, description="本次响应是否应用了 Rerank 排序")
    results: list[RetrievalResult] = Field(
        default_factory=list,
        description="按最终相关性顺序排列的 Chunk 检索结果列表；document 模式下为空列表",
    )
    document: RetrievalDocument | None = Field(
        default=None,
        description="全文召回模式返回的文档原文；非 document 模式下为 null",
    )
