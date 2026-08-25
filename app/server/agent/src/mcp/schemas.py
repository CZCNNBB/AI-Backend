from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


MCPTransport = Literal["http", "streamable-http", "sse"]
RecordStatus = Literal["enabled", "disabled"]


class AgentMCPToolUpsertRequest(BaseModel):
    """新增或更新平台 MCP 工具的请求。"""

    original_mcp_code: str | None = Field(default=None, description="编辑时用于定位原记录的 MCP 工具编码")
    mcp_code: str = Field(..., min_length=1, max_length=150, description="平台 MCP 工具唯一编码")
    name: str = Field(..., min_length=1, max_length=255, description="MCP 服务中的真实工具名")
    description: str | None = Field(default=None, description="工具描述")
    base_url: str = Field(..., min_length=1, description="MCP 服务访问地址，例如 http://127.0.0.1:8091/mcp/")
    transport: MCPTransport = Field(default="http", description="MCP 传输协议")
    auth_type: str | None = Field(default=None, max_length=50, description="认证类型，第一阶段可为空")
    auth_config: dict[str, Any] | None = Field(default=None, description="认证配置 JSON，第一阶段按 MCP 客户端配置透传")
    input_schema: dict[str, Any] | None = Field(default=None, description="工具输入参数 JSON Schema")
    output_schema: dict[str, Any] | None = Field(default=None, description="工具输出参数 JSON Schema")
    status: RecordStatus = Field(default="enabled", description="工具状态")

    @field_validator("original_mcp_code", "mcp_code", "name", "description", "base_url", "auth_type")
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        """清理文本字段两侧空白，避免不可见字符造成重复配置。"""
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class AgentMCPToolDetailRequest(BaseModel):
    """查询单个 MCP 工具详情的请求。"""

    mcp_code: str = Field(..., min_length=1, description="平台 MCP 工具编码")

    @field_validator("mcp_code")
    @classmethod
    def strip_mcp_code(cls, value: str) -> str:
        """清理 MCP 工具编码。"""
        return value.strip()


class AgentMCPToolSearchRequest(BaseModel):
    """分页查询 MCP 工具列表的请求。"""

    keyword: str | None = Field(default=None, description="关键字，匹配工具编码、名称、描述和地址")
    status: RecordStatus | None = Field(default=None, description="工具状态过滤")
    base_url: str | None = Field(default=None, description="MCP 服务地址过滤")
    page: int = Field(default=1, ge=1, description="页码")
    page_size: int = Field(default=20, ge=1, le=100, description="每页数量")

    @field_validator("keyword", "base_url")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        """清理查询条件中的可选文本字段。"""
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class AgentMCPToolDeleteRequest(BaseModel):
    """批量删除 MCP 工具的请求。"""

    mcp_codes: list[str] = Field(..., min_length=1, description="待删除的 MCP 工具编码列表")

    @field_validator("mcp_codes")
    @classmethod
    def normalize_mcp_codes(cls, value: list[str]) -> list[str]:
        """清理 MCP 工具编码列表并移除空值。"""
        normalized = [item.strip() for item in value if item and item.strip()]
        if not normalized:
            raise ValueError("mcp_codes 不能为空")
        return normalized


class AgentMCPToolTestRequest(BaseModel):
    """测试 MCP 工具或 MCP 服务连接的请求。"""

    mcp_code: str | None = Field(default=None, description="已保存的 MCP 工具编码")
    base_url: str | None = Field(default=None, description="临时测试的 MCP 服务地址")
    transport: MCPTransport = Field(default="http", description="MCP 传输协议")
    auth_config: dict[str, Any] | None = Field(default=None, description="临时测试的认证配置")

    @field_validator("mcp_code", "base_url")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        """清理可选文本字段。"""
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @model_validator(mode="after")
    def validate_lookup_source(self) -> "AgentMCPToolTestRequest":
        """确保连接测试至少有已保存工具编码或临时服务地址。"""
        if not self.mcp_code and not self.base_url:
            raise ValueError("mcp_code 和 base_url 至少需要提供一个")
        return self


class AgentMCPToolSyncRequest(BaseModel):
    """从某个 MCP 服务同步工具列表的请求。"""

    base_url: str = Field(..., min_length=1, description="MCP 服务访问地址")
    transport: MCPTransport = Field(default="http", description="MCP 传输协议")
    code_prefix: str | None = Field(default=None, max_length=100, description="工具编码前缀，例如 job；为空时使用工具原名")
    auth_type: str | None = Field(default=None, max_length=50, description="认证类型，第一阶段可为空")
    auth_config: dict[str, Any] | None = Field(default=None, description="认证配置 JSON")
    overwrite: bool = Field(default=True, description="工具已存在时是否覆盖描述、Schema 和地址配置")

    @field_validator("base_url", "code_prefix", "auth_type")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        """清理同步请求中的文本字段。"""
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class AgentMCPToolInvokeRequest(BaseModel):
    """直接测试调用某个 MCP 工具的请求。"""

    mcp_code: str = Field(..., min_length=1, description="平台 MCP 工具编码")
    args: dict[str, Any] = Field(default_factory=dict, description="工具调用参数")

    @field_validator("mcp_code")
    @classmethod
    def strip_mcp_code(cls, value: str) -> str:
        """清理 MCP 工具编码。"""
        return value.strip()


class AgentMCPToolView(BaseModel):
    """平台 MCP 工具返回视图。"""

    id: int | None = Field(default=None, description="主键 ID")
    mcp_code: str = Field(..., description="平台 MCP 工具编码")
    name: str = Field(..., description="MCP 真实工具名")
    description: str | None = Field(default=None, description="工具描述")
    base_url: str = Field(..., description="MCP 服务访问地址")
    transport: str = Field(..., description="MCP 传输协议")
    auth_type: str | None = Field(default=None, description="认证类型")
    auth_config: dict[str, Any] | None = Field(default=None, description="认证配置")
    input_schema: dict[str, Any] | None = Field(default=None, description="输入参数 Schema")
    output_schema: dict[str, Any] | None = Field(default=None, description="输出参数 Schema")
    status: str = Field(..., description="工具状态")
    created_at: str | None = Field(default=None, description="创建时间")
    updated_at: str | None = Field(default=None, description="更新时间")


class AgentMCPToolSearchResponse(BaseModel):
    """MCP 工具分页查询响应。"""

    total: int = Field(default=0, description="总数量")
    page: int = Field(default=1, description="页码")
    page_size: int = Field(default=20, description="每页数量")
    items: list[AgentMCPToolView] = Field(default_factory=list, description="MCP 工具列表")


class AgentMCPToolSyncResponse(BaseModel):
    """MCP 工具同步响应。"""

    base_url: str = Field(..., description="MCP 服务访问地址")
    synced: int = Field(default=0, description="本次同步的工具数量")
    items: list[AgentMCPToolView] = Field(default_factory=list, description="已同步的平台 MCP 工具列表")


class AgentMCPToolTestResponse(BaseModel):
    """MCP 连接测试响应。"""

    ok: bool = Field(default=False, description="是否连接成功")
    tool_count: int = Field(default=0, description="读取到的工具数量")
    tools: list[dict[str, Any]] = Field(default_factory=list, description="MCP 工具摘要列表")
