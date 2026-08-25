from typing import Any

from pydantic import BaseModel, Field


class AgentToolInfo(BaseModel):
    """Agent 工具详情视图。"""

    name: str = Field(..., description="工具名称")
    description: str = Field(default="", description="工具说明")
    group: str = Field(default="regular", description="工具分组，例如 mcp、planning、a2a")
    invokable: bool = Field(default=True, description="是否允许通过工具调试接口直接调用")
    template_selectable: bool = Field(default=True, description="是否允许配置到 Agent 模板 config.tools")
    activation_mode: str = Field(default="template", description="工具启用方式：template=模板选择，feature=能力开关自动挂载")
    invoke_note: str | None = Field(default=None, description="不可直接调用或调用前置条件说明")
    args_schema: dict[str, Any] = Field(default_factory=dict, description="工具参数 JSON Schema")


class AgentToolInvokeRequest(BaseModel):
    """Agent 工具调试调用请求。"""

    tool_name: str = Field(..., min_length=1, description="工具名称")
    args: dict[str, Any] = Field(default_factory=dict, description="工具调用参数")


class AgentToolInvokeResponse(BaseModel):
    """Agent 工具调试调用响应。"""

    tool_name: str = Field(..., description="工具名称")
    args: dict[str, Any] = Field(default_factory=dict, description="本次调用参数")
    result: Any = Field(default=None, description="工具返回结果")
