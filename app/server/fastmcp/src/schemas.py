from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


HTTPMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
ParameterLocation = Literal["path", "query", "header", "body"]
ParameterSource = Literal["tool", "runtime", "static"]
ParameterType = Literal["string", "integer", "number", "boolean", "object", "array"]
AuthType = Literal["none", "bearer", "basic", "api_key"]
RecordStatus = Literal["draft", "enabled", "disabled"]


class MCPToolParameter(BaseModel):
    """描述一个 MCP 参数如何映射到目标 HTTP API。"""

    name: str = Field(..., min_length=1, max_length=150, description="MCP Tool 参数名")
    target: str | None = Field(default=None, description="目标 API 参数名；不填时与 name 相同")
    location: ParameterLocation = Field(..., description="参数进入 path、query、header 或 JSON body")
    source: ParameterSource = Field(default="tool", description="参数来自模型、运行时上下文或固定值")
    data_type: ParameterType = Field(default="string", description="参数 JSON 类型")
    required: bool = Field(default=False, description="模型参数是否必填")
    description: str | None = Field(default=None, description="给 Agent 看的参数说明")
    default: Any = Field(default=None, description="模型参数默认值")
    value: Any = Field(default=None, description="source=static 时使用的固定值")
    runtime_path: str | None = Field(default=None, description="source=runtime 时从 inputs 读取的点分路径")
    item_schema: dict[str, Any] | None = Field(default=None, description="object/array 参数的补充 JSON Schema")

    @field_validator("name", "target", "runtime_path", "description")
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        """清理参数配置中的文本，并把空字符串统一转换为空值。"""
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @model_validator(mode="after")
    def fill_mapping_defaults(self) -> "MCPToolParameter":
        """补齐目标字段和运行时路径，并校验来源相关配置。"""
        self.target = self.target or self.name
        if self.source == "runtime":
            self.runtime_path = self.runtime_path or self.name
        if self.location == "path" and self.source == "tool":
            # URL path 参数无法安全省略，因此对模型暴露时必须视为必填。
            self.required = True
        return self


class MCPToolUpsertRequest(BaseModel):
    """新增或更新一个 HTTP API 转换型 MCP Tool。"""

    name: str = Field(..., min_length=1, max_length=150, description="Agent 配置引用的 MCP Tool 名称")
    description: str | None = Field(default=None, description="工具用途说明")
    api_url: str = Field(..., min_length=1, description="目标业务 HTTP API 完整地址")
    http_method: HTTPMethod = Field(default="POST", description="目标 API 请求方法")
    static_headers: dict[str, Any] = Field(default_factory=dict, description="固定发送的 HTTP 请求头")
    parameters: list[MCPToolParameter] = Field(default_factory=list, description="API 参数映射列表")
    auth_type: AuthType = Field(default="none", description="目标 API 认证类型")
    auth_config: dict[str, Any] = Field(default_factory=dict, description="仅由平台使用的认证配置")
    output_schema: dict[str, Any] | None = Field(default=None, description="可选的工具输出 JSON Schema")
    timeout_seconds: float = Field(default=30.0, gt=0, le=600, description="目标 API 超时时间")
    status: RecordStatus = Field(default="draft", description="draft 不发布，enabled 发布为 MCP Tool")

    @field_validator("name", "api_url")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        """清理必填文本，并拒绝只包含空白字符的值。"""
        stripped = value.strip()
        if not stripped:
            raise ValueError("必填文本字段不能为空")
        return stripped

    @field_validator("description")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        """清理可选文本字段。"""
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @model_validator(mode="after")
    def validate_parameter_names(self) -> "MCPToolUpsertRequest":
        """保证参数名称唯一，避免同一输入被多个不明确规则重复消费。"""
        parameter_names = [parameter.name for parameter in self.parameters]
        duplicate_names = sorted({name for name in parameter_names if parameter_names.count(name) > 1})
        if duplicate_names:
            raise ValueError(f"参数名称不能重复: {', '.join(duplicate_names)}")
        return self

    def build_input_schema(self) -> dict[str, Any]:
        """根据 source=tool 的参数自动生成 FastMCP 输入 JSON Schema。"""
        properties: dict[str, Any] = {}
        required_names: list[str] = []

        for parameter in self.parameters:
            if parameter.source != "tool":
                # runtime/static 参数由平台注入，不能暴露给模型填写。
                continue

            property_schema = dict(parameter.item_schema or {})
            property_schema.setdefault("type", parameter.data_type)
            if parameter.description:
                property_schema["description"] = parameter.description
            if parameter.default is not None:
                property_schema["default"] = parameter.default
            properties[parameter.name] = property_schema

            if parameter.required:
                required_names.append(parameter.name)

        input_schema: dict[str, Any] = {
            "type": "object",
            "properties": properties,
            "additionalProperties": False,
        }
        if required_names:
            input_schema["required"] = required_names
        return input_schema


class MCPToolDetailRequest(BaseModel):
    """查询单个 MCP Tool 详情的请求。"""

    name: str = Field(..., min_length=1, description="MCP Tool 名称")

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        """清理 MCP Tool 名称。"""
        stripped = value.strip()
        if not stripped:
            raise ValueError("name 不能为空")
        return stripped


class MCPToolSearchRequest(BaseModel):
    """分页查询 MCP Tool 列表的请求。"""

    keyword: str | None = Field(default=None, description="匹配名称、描述和目标 API 地址")
    status: RecordStatus | None = Field(default=None, description="状态过滤")
    api_url: str | None = Field(default=None, description="目标 API 地址过滤")
    page: int = Field(default=1, ge=1, description="页码")
    page_size: int = Field(default=20, ge=1, le=100, description="每页数量")

    @field_validator("keyword", "api_url")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        """清理查询条件中的可选文本。"""
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class MCPToolDeleteRequest(BaseModel):
    """批量删除 MCP Tool 的请求。"""

    names: list[str] = Field(..., min_length=1, description="待删除的 MCP Tool 名称")

    @field_validator("names")
    @classmethod
    def normalize_names(cls, value: list[str]) -> list[str]:
        """清理工具名称并移除空值和重复值。"""
        normalized = list(dict.fromkeys(item.strip() for item in value if item and item.strip()))
        if not normalized:
            raise ValueError("names 不能为空")
        return normalized


class MCPToolPublishRequest(BaseModel):
    """发布或停用 MCP Tool 的请求。"""

    name: str = Field(..., min_length=1, description="MCP Tool 名称")
    enabled: bool = Field(default=True, description="true 发布，false 停用")

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        """清理 MCP Tool 名称。"""
        stripped = value.strip()
        if not stripped:
            raise ValueError("name 不能为空")
        return stripped


class MCPToolTestRequest(BaseModel):
    """测试已保存配置或尚未保存的临时 API 配置。"""

    name: str | None = Field(default=None, description="已保存的 MCP Tool 名称")
    tool: MCPToolUpsertRequest | None = Field(default=None, description="尚未保存的临时 API 配置")
    args: dict[str, Any] = Field(default_factory=dict, description="本次测试使用的 Tool 参数")
    runtime_inputs: dict[str, Any] = Field(default_factory=dict, description="测试 runtime 参数映射时使用的模拟 inputs")

    @model_validator(mode="after")
    def validate_source(self) -> "MCPToolTestRequest":
        """保证测试请求只选择一种配置来源。"""
        if bool(self.name) == bool(self.tool):
            raise ValueError("name 和 tool 必须且只能提供一个")
        if self.name:
            self.name = self.name.strip()
        return self


class MCPToolInvokeRequest(BaseModel):
    """直接调用已发布 MCP Tool 的管理接口请求。"""

    name: str = Field(..., min_length=1, description="MCP Tool 名称")
    args: dict[str, Any] = Field(default_factory=dict, description="Tool 调用参数")
    runtime_inputs: dict[str, Any] = Field(default_factory=dict, description="可选的模拟运行时 inputs")

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        """清理 MCP Tool 名称。"""
        stripped = value.strip()
        if not stripped:
            raise ValueError("name 不能为空")
        return stripped


class MCPToolView(BaseModel):
    """MCP Tool 管理接口返回视图。"""

    id: int | None = None
    name: str
    description: str | None = None
    api_url: str
    http_method: str
    static_headers: dict[str, Any] = Field(default_factory=dict)
    parameters: list[MCPToolParameter] = Field(default_factory=list)
    auth_type: str
    auth_config: dict[str, Any] = Field(default_factory=dict)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] | None = None
    timeout_seconds: float
    status: str
    created_at: str | None = None
    updated_at: str | None = None


class MCPToolSearchResponse(BaseModel):
    """MCP Tool 分页查询响应。"""

    total: int = 0
    page: int = 1
    page_size: int = 20
    items: list[MCPToolView] = Field(default_factory=list)


class MCPToolTestResponse(BaseModel):
    """目标 HTTP API 连通与请求组装测试结果。"""

    ok: bool = False
    status_code: int | None = None
    elapsed_ms: int | None = None
    data: Any = None
