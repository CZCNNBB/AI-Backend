from typing import Any

from pydantic import BaseModel, Field


class AgentConversationSearchRequest(BaseModel):
    """查询 Agent 会话列表的请求参数。"""

    external_user_id: str = Field(..., min_length=1, max_length=150, description="外部业务用户 ID")
    agent_id: str | None = Field(default=None, min_length=1, max_length=100, description="可选 Agent 模板 ID")
    conversation_id: str | None = Field(default=None, description="可选会话 ID，传入时精确匹配")
    page: int = Field(default=1, ge=1, description="页码")
    page_size: int = Field(default=20, ge=1, le=100, description="每页数量")


class AgentConversationMessagesRequest(BaseModel):
    """查询某个 Agent 会话消息列表的请求参数。"""

    external_user_id: str = Field(..., min_length=1, max_length=150, description="外部业务用户 ID")
    conversation_id: str = Field(..., min_length=1, description="会话 ID")
    limit: int = Field(default=50, ge=1, le=200, description="最多返回多少条最近消息")


class AgentConversationView(BaseModel):
    """返回给接口调用方的 Agent 会话视图。"""

    conversation_id: str = Field(..., description="会话 ID")
    external_user_id: str = Field(..., description="外部业务用户 ID")
    agent_id: str = Field(..., description="该会话所属的 Agent 模板 ID")
    title: str | None = Field(default=None, description="会话标题")
    status: str = Field(default="active", description="会话状态")
    metadata: dict[str, Any] = Field(default_factory=dict, description="会话扩展元数据")
    created_at: str | None = Field(default=None, description="创建时间")
    updated_at: str | None = Field(default=None, description="更新时间")


class AgentConversationSearchResponse(BaseModel):
    """Agent 会话分页查询响应。"""

    total: int = Field(default=0, description="总数量")
    page: int = Field(default=1, description="页码")
    page_size: int = Field(default=20, description="每页数量")
    items: list[AgentConversationView] = Field(default_factory=list, description="会话列表")


class AgentConversationMessagesResponse(BaseModel):
    """Agent 会话消息查询响应。"""

    conversation_id: str = Field(..., description="会话 ID")
    messages: list["ContextMessageView"] = Field(default_factory=list, description="消息列表")


class ContextMessageCreate(BaseModel):
    """创建 Agent 历史消息时使用的输入结构。"""

    conversation_id: str = Field(..., description="会话 ID")
    role: str = Field(..., description="消息角色，例如 user、assistant、tool、agent")
    message_type: str = Field(..., description="消息类型，例如 user_message、assistant_message、tool_call")
    content: str | None = Field(default=None, description="文本内容")

    message_id: str | None = Field(default=None, description="消息唯一 ID，不传则自动生成")
    parent_message_id: str | None = Field(default=None, description="父消息 ID")
    structured_content: dict[str, Any] | None = Field(default=None, description="结构化内容")
    tool_name: str | None = Field(default=None, description="工具名称")
    tool_call_id: str | None = Field(default=None, description="工具调用 ID")
    status: str = Field(default="success", description="消息状态")
    error_message: str | None = Field(default=None, description="错误信息")
    metadata: dict[str, Any] = Field(default_factory=dict, description="扩展元数据")


class ContextMessageView(BaseModel):
    """返回给业务层使用的 Agent 历史消息视图。"""

    message_id: str
    role: str
    message_type: str
    content: str | None = None
    structured_content: dict[str, Any] | None = None
    tool_name: str | None = None
    tool_call_id: str | None = None
    status: str = "success"
    error_message: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str | None = Field(default=None, description="消息创建时间")
