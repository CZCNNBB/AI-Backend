"""业务平台管理和请求身份相关的 Pydantic Schema。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


PlatformStatus = Literal["enabled", "disabled"]


class PlatformPrincipal(BaseModel):
    """平台 API Key 认证成功后生成的可信请求身份。"""

    platform_id: int = Field(..., description="业务平台数据库主键")
    platform_code: str = Field(..., description="业务平台稳定编码")
    platform_name: str = Field(..., description="业务平台展示名称")
    api_key_id: int = Field(..., description="本次请求使用的平台 API Key 记录 ID")


class BusinessPlatformUpsertRequest(BaseModel):
    """创建或更新业务平台的请求参数。"""

    platform_code: str = Field(..., min_length=1, max_length=100, description="业务平台稳定编码")
    platform_name: str = Field(..., min_length=1, max_length=200, description="业务平台展示名称")
    description: str | None = Field(default=None, description="业务平台说明")
    status: PlatformStatus = Field(default="enabled", description="业务平台状态")

    @field_validator("platform_code", "platform_name")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        """清理必填文本两侧空白。"""
        return value.strip()

    @field_validator("description")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        """清理可选说明并把空字符串转换为空值。"""
        if value is None:
            return None
        return value.strip() or None


class BusinessPlatformDetailRequest(BaseModel):
    """查询单个业务平台详情的请求参数。"""

    platform_code: str = Field(..., min_length=1, max_length=100, description="业务平台稳定编码")

    @field_validator("platform_code")
    @classmethod
    def normalize_platform_code(cls, value: str) -> str:
        """清理业务平台编码。"""
        return value.strip()


class BusinessPlatformSearchRequest(BaseModel):
    """分页查询业务平台的请求参数。"""

    keyword: str | None = Field(default=None, description="匹配平台编码、名称和说明")
    status: PlatformStatus | None = Field(default=None, description="平台状态")
    page: int = Field(default=1, ge=1, description="页码")
    page_size: int = Field(default=20, ge=1, le=100, description="每页数量")


class BusinessPlatformView(BaseModel):
    """业务平台管理接口返回视图。"""

    id: int
    platform_code: str
    platform_name: str
    description: str | None = None
    status: str
    created_at: str | None = None
    updated_at: str | None = None


class BusinessPlatformSearchResponse(BaseModel):
    """业务平台分页查询响应。"""

    total: int = 0
    page: int = 1
    page_size: int = 20
    items: list[BusinessPlatformView] = Field(default_factory=list)


class BusinessPlatformAPIKeyCreateRequest(BaseModel):
    """为业务平台签发 API Key 的请求参数。"""

    platform_code: str = Field(..., min_length=1, max_length=100, description="业务平台稳定编码")
    key_name: str = Field(default="default", min_length=1, max_length=100, description="凭证用途名称")
    expires_at: datetime | None = Field(default=None, description="可选过期时间")

    @field_validator("platform_code", "key_name")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        """清理平台编码和凭证名称。"""
        return value.strip()


class BusinessPlatformAPIKeyCreateResponse(BaseModel):
    """API Key 签发响应，完整密钥可供内网管理端调试使用。"""

    id: int
    platform_id: int
    key_name: str
    key_prefix: str
    api_key: str
    expires_at: str | None = None


class BusinessPlatformAPIKeyDisableRequest(BaseModel):
    """停用平台 API Key 的请求参数。"""

    api_key_id: int = Field(..., ge=1, description="API Key 记录 ID")


class BusinessPlatformAPIKeyListRequest(BaseModel):
    """查询业务平台全部 API Key 的请求参数。"""

    platform_code: str = Field(..., min_length=1, max_length=100, description="业务平台稳定编码")

    @field_validator("platform_code")
    @classmethod
    def normalize_platform_code(cls, value: str) -> str:
        """清理业务平台编码两侧空白。"""
        return value.strip()


class BusinessPlatformAPIKeyView(BaseModel):
    """内网业务平台管理页面使用的完整 API Key 视图。"""

    id: int
    platform_id: int
    key_name: str
    key_prefix: str
    api_key: str = Field(..., description="完整明文 API Key，请勿写入日志")
    status: str
    expires_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class AgentPlatformAccessRequest(BaseModel):
    """查询 Agent 关联业务平台和调试凭证的请求参数。"""

    agent_id: str = Field(..., min_length=1, max_length=100, description="Agent 模板 ID")

    @field_validator("agent_id")
    @classmethod
    def normalize_agent_id(cls, value: str) -> str:
        """清理 Agent 模板 ID 两侧空白。"""
        return value.strip()


class AgentPlatformAccessOption(BaseModel):
    """Agent 调用页可选择的业务平台及默认调试 API Key。"""

    platform_id: int = Field(..., description="业务平台数据库主键")
    platform_code: str = Field(..., description="业务平台稳定编码")
    platform_name: str = Field(..., description="业务平台展示名称")
    api_key_id: int | None = Field(default=None, description="默认可用 API Key 记录 ID")
    api_key_name: str | None = Field(default=None, description="默认可用 API Key 用途名称")
    api_key: str | None = Field(default=None, description="内网管理端调试使用的完整 API Key")
