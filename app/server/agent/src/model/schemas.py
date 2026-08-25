from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


ModelType = Literal["chat", "embedding", "rerank"]


class ModelConfigUpsertRequest(BaseModel):
    """Request body for creating or updating one model config."""

    # original_model_code is only used when editing an existing config and renaming model_code.
    original_model_code: str | None = Field(default=None, max_length=100, description="Original model code used as update lookup key")
    model_code: str = Field(..., min_length=1, max_length=100, description="Platform model code")
    model_name: str = Field(..., min_length=1, max_length=255, description="Provider-side model name")
    model_type: ModelType = Field(..., description="Model type: chat, embedding, rerank")

    base_url: str = Field(..., min_length=1, description="OpenAI-compatible model service base URL")
    api_key: str | None = Field(default=None, description="Model service API key; saved as a normal local config value")
    api_type: str = Field(default="openai_compatible", max_length=50, description="Internal protocol type; defaults to OpenAI compatible")

    support_stream: bool = Field(default=False, description="Whether streaming output is supported")
    support_tool_calling: bool = Field(default=False, description="Whether tool calling is supported")
    support_structured_output: bool = Field(default=False, description="Whether structured output is supported")
    is_multimodal: bool = Field(default=False, description="Whether this model supports multimodal input")

    enabled: bool = Field(default=True, description="Whether this model config is enabled")

    extra_config: dict[str, Any] | None = Field(default=None, description="Extra model config")
    description: str | None = Field(default=None, description="Model description")

    @model_validator(mode="after")
    def validate_embedding_dimension(self) -> "ModelConfigUpsertRequest":
        """Embedding 模型必须配置正整数向量维度。"""
        if self.model_type != "embedding":
            return self
        extra_config = self.extra_config or {}
        dimension = extra_config.get("dimension")
        if not isinstance(dimension, int) or isinstance(dimension, bool) or dimension <= 0:
            raise ValueError("Embedding 模型必须在 extra_config.dimension 配置正整数向量维度")
        batch_size = extra_config.get("batch_size", 32)
        if (
            not isinstance(batch_size, int)
            or isinstance(batch_size, bool)
            or not 1 <= batch_size <= 256
        ):
            raise ValueError("Embedding 模型 extra_config.batch_size 必须是 1 到 256 的整数")
        return self

    @field_validator("model_code", "model_name", "model_type", "base_url", "api_type")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        """Trim required text fields to avoid invisible config differences."""
        return value.strip()

    @field_validator("original_model_code", "api_key", "description")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        """Trim optional text fields; empty strings are saved as None."""
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class ModelConfigDetailRequest(BaseModel):
    """Request body for querying one model config."""

    model_code: str = Field(..., min_length=1, description="Platform model code")

    @field_validator("model_code")
    @classmethod
    def strip_model_code(cls, value: str) -> str:
        """Trim model_code before querying."""
        return value.strip()


class ModelConfigSearchRequest(BaseModel):
    """Request body for searching model configs."""

    keyword: str | None = Field(default=None, description="Keyword matched against model_code, model_name, description")
    model_type: ModelType | None = Field(default=None, description="Model type filter")
    enabled: bool | None = Field(default=None, description="Enabled status filter")
    page: int = Field(default=1, ge=1, description="Page number")
    page_size: int = Field(default=20, ge=1, le=100, description="Page size")

    @field_validator("keyword")
    @classmethod
    def normalize_keyword(cls, value: str | None) -> str | None:
        """Trim keyword and treat empty strings as not provided."""
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class ModelConfigDeleteRequest(BaseModel):
    """Request body for deleting model configs."""

    model_codes: list[str] = Field(..., min_length=1, description="Model codes to delete")

    @field_validator("model_codes")
    @classmethod
    def normalize_model_codes(cls, value: list[str]) -> list[str]:
        """Trim model codes and remove empty values."""
        return [item.strip() for item in value if item and item.strip()]


class ModelConfigView(BaseModel):
    """Model config response view. API key is returned because this is a local deployment config."""

    id: int | None = Field(default=None, description="Primary key")
    model_code: str = Field(..., description="Platform model code")
    model_name: str = Field(..., description="Provider-side model name")
    model_type: str = Field(..., description="Model type")

    base_url: str = Field(..., description="Model service base URL")
    api_key: str | None = Field(default=None, description="Model service API key")
    api_type: str = Field(default="openai_compatible", description="Internal protocol type")

    support_stream: bool = Field(default=False, description="Whether streaming output is supported")
    support_tool_calling: bool = Field(default=False, description="Whether tool calling is supported")
    support_structured_output: bool = Field(default=False, description="Whether structured output is supported")
    is_multimodal: bool = Field(default=False, description="Whether this model supports multimodal input")

    enabled: bool = Field(default=True, description="Whether this model config is enabled")

    extra_config: dict[str, Any] | None = Field(default=None, description="Extra model config")
    description: str | None = Field(default=None, description="Model description")

    created_at: str | None = Field(default=None, description="Created time")
    updated_at: str | None = Field(default=None, description="Updated time")


class ModelConfigSearchResponse(BaseModel):
    """Paged model config search response."""

    total: int = Field(default=0, description="Total count")
    page: int = Field(default=1, description="Page number")
    page_size: int = Field(default=20, description="Page size")
    items: list[ModelConfigView] = Field(default_factory=list, description="Model config items")
