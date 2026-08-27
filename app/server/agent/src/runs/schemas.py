from typing import Any, Literal

from pydantic import BaseModel, Field


class AgentRunSearchRequest(BaseModel):
    """查询 Agent 运行记录列表的请求参数。"""

    external_user_id: str = Field(..., min_length=1, max_length=150, description="外部业务用户 ID")
    run_id: str | None = Field(default=None, description="运行 ID，支持精确匹配")
    run_type: Literal["main", "sub"] | None = Field(default=None, description="运行类型：main=主 Agent，sub=A2A 子 Agent")
    parent_run_id: str | None = Field(default=None, description="父级运行 ID，用于查询某次主 Agent 触发的子 Agent")
    agent_id: str | None = Field(default=None, description="Agent 模板 ID")
    conversation_id: str | None = Field(default=None, description="会话 ID")
    status: str | None = Field(default=None, description="运行状态：running/success/failed")
    page: int = Field(default=1, ge=1, description="页码，从 1 开始")
    page_size: int = Field(default=20, ge=1, le=100, description="每页数量")


class AgentRunDetailRequest(BaseModel):
    """查询单条 Agent 运行记录详情的请求参数。"""

    run_id: str = Field(..., min_length=1, description="运行 ID")
    external_user_id: str = Field(..., min_length=1, max_length=150, description="外部业务用户 ID")


class AgentRunChainRequest(BaseModel):
    """查询某次主 Agent 运行链路的请求参数。"""

    run_id: str = Field(..., min_length=1, description="主 Agent 运行 ID")
    external_user_id: str = Field(..., min_length=1, max_length=150, description="外部业务用户 ID")


class AgentRunView(BaseModel):
    """Agent 运行记录返回视图。"""

    run_id: str = Field(..., description="运行 ID")
    platform_id: int = Field(..., description="业务平台 ID")
    external_user_id: str = Field(..., description="外部业务用户 ID")
    run_type: str = Field(default="main", description="运行类型：main/sub")
    parent_run_id: str | None = Field(default=None, description="父级运行 ID")
    agent_id: str | None = Field(default=None, description="Agent 模板 ID")
    conversation_id: str | None = Field(default=None, description="会话 ID")
    user_message_id: str | None = Field(default=None, description="用户消息 ID")
    assistant_message_id: str | None = Field(default=None, description="助手消息 ID")
    query: str | None = Field(default=None, description="运行输入")
    answer: str | None = Field(default=None, description="运行输出")
    status: str = Field(default="running", description="运行状态")
    error_message: str | None = Field(default=None, description="错误信息")
    elapsed_ms: float | None = Field(default=None, description="运行耗时，单位毫秒")
    metadata: dict[str, Any] = Field(default_factory=dict, description="扩展元数据")
    started_at: str | None = Field(default=None, description="开始时间")
    finished_at: str | None = Field(default=None, description="结束时间")


class AgentRunSearchResponse(BaseModel):
    """Agent 运行记录分页查询响应。"""

    total: int = Field(default=0, description="总数量")
    page: int = Field(default=1, description="页码")
    page_size: int = Field(default=20, description="每页数量")
    items: list[AgentRunView] = Field(default_factory=list, description="运行记录列表")


class AgentRunChainResponse(BaseModel):
    """Agent 主子运行链路查询响应。"""

    run_id: str = Field(..., description="主 Agent 运行 ID")
    items: list[AgentRunView] = Field(default_factory=list, description="主运行和子运行记录")
