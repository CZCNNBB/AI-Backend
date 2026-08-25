"""知识库向量化请求与响应模型。"""

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EmbeddingModelConfig(BaseModel):
    """单次向量化使用的模型配置。"""

    model_code: str = Field(..., min_length=1, description="平台 Embedding 模型编码")
    dimension: int = Field(..., ge=1, description="模型预期向量维度")


class EmbeddingInput(BaseModel):
    """临时向量化输入；正式入库由 IngestionService 统一编排。"""

    model_config = ConfigDict(populate_by_name=True)

    text: str = Field(..., min_length=1, description="待向量化文本")
    embedding_model_config: EmbeddingModelConfig | None = Field(
        default=None,
        alias="model_config",
        description="可选模型配置；不传时使用知识库默认配置",
    )
    extra_params: dict[str, Any] = Field(default_factory=dict, description="透传给模型服务的附加参数")

    @field_validator("extra_params")
    @classmethod
    def validate_extra_params(cls, extra_params: dict[str, Any]) -> dict[str, Any]:
        """禁止附加参数覆盖由服务维护的 OpenAI Embedding 核心字段。"""
        conflicts = sorted({"model", "input", "dimensions"}.intersection(extra_params))
        if conflicts:
            raise ValueError(f"extra_params 不能覆盖保留字段: {conflicts}")
        return extra_params


class EmbeddingOutput(BaseModel):
    """临时向量化输出。"""

    model_code: str = Field(..., description="实际使用的平台模型编码")
    dimension: int = Field(..., ge=1, description="实际向量维度")
    embedding: list[float] = Field(..., description="文本向量")


class PersistentVectorRecord(BaseModel):
    """未来入库流程写入 Milvus 时使用的内部向量记录。"""

    collection_name: str = Field(..., min_length=1, max_length=255)
    chunk_id: str = Field(..., min_length=1, max_length=100)
    file_id: str = Field(..., min_length=1, max_length=100)
    source: str = Field(..., min_length=1)
    chunk_index: int = Field(..., ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("metadata")
    @classmethod
    def validate_metadata(cls, metadata: dict[str, Any]) -> dict[str, Any]:
        """限制元数据大小，并清理标题层级中的空值。"""
        try:
            serialized = json.dumps(metadata, ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("metadata 必须可以序列化为 JSON") from exc
        if len(serialized) > 8192:
            raise ValueError("metadata JSON 长度不能超过 8192 个字符")

        headers = metadata.get("headers")
        if headers is None:
            return metadata
        if not isinstance(headers, dict):
            raise ValueError("metadata.headers 必须是对象")

        normalized = dict(metadata)
        normalized_headers = {
            str(key).strip(): str(value).strip()
            for key, value in headers.items()
            if str(key).strip() and str(value).strip()
        }
        if normalized_headers:
            normalized["headers"] = normalized_headers
        else:
            normalized.pop("headers", None)
        return normalized


class PersistentVectorWrite(BaseModel):
    """单条待写入 Milvus 的文本、向量和索引元数据。"""

    text: str = Field(..., min_length=1)
    embedding: list[float] = Field(..., min_length=1)
    record: PersistentVectorRecord


# 保留旧内部名称，避免 Milvus 适配器在本次目录整理中承担无关改动。
PersistentOptions = PersistentVectorRecord
