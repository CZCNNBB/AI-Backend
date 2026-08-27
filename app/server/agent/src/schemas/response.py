from typing import Any

from pydantic import BaseModel, Field

from app.server.agent.src.tools.schemas import AgentToolInfo


class ModelConfigResponse(BaseModel):
    """当前模型资源池摘要响应。"""

    available_models: list[str] = Field(default_factory=list, description="全部可用模型编码")
    chat_models: list[str] = Field(default_factory=list, description="已启用 chat 模型编码")
    embedding_models: list[str] = Field(default_factory=list, description="已启用 embedding 模型编码")
    rerank_models: list[str] = Field(default_factory=list, description="已启用 rerank 模型编码")
    langsmith_tracing: bool = Field(default=False, description="是否启用 LangSmith 追踪")
    langsmith_endpoint: str = Field(default="", description="LangSmith 地址")
    langsmith_project: str = Field(default="", description="LangSmith 项目名")
    has_langsmith_api_key: bool = Field(default=False, description="是否已经配置 LangSmith API Key")


class AgentCapabilityResponse(BaseModel):
    """Agent 服务能力响应。"""

    service_name: str = Field(..., description="服务名称")
    modules: list[str] = Field(default_factory=list, description="Agent 服务内部模块")
    enabled_features: list[str] = Field(default_factory=list, description="当前可用能力")
    registered_tools: list[str] = Field(default_factory=list, description="当前已注册的 Agent 工具名称")
    tools: list[AgentToolInfo] = Field(default_factory=list, description="当前可展示的 Agent 工具详情")


class AgentRunResponse(BaseModel):
    """通用 Agent 运行响应模型。"""

    run_id: str = Field(default="", description="Agent 本次运行 ID")
    conversation_id: str = Field(default="", description="AI-backend 生成或沿用的业务会话 ID")
    answer: str = Field(default="", description="Agent 输出文本")
    tool_results: list[dict[str, Any]] = Field(default_factory=list, description="本次实际完成的工具执行结果")
