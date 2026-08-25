from typing import Any

from pydantic import BaseModel, Field

from app.server.agent.src.schemas.context_summarization import ContextSummarizationConfig
from app.server.agent.src.schemas.request import AgentA2AConfig


class AgentFeatureConfig(BaseModel):
    """Agent 内部装配能力开关。

    这个配置只在 agent 服务内部使用，不直接暴露给 API 调用方。
    API 层使用 AgentOptionalFeatures 描述业务能力，AgentService 再把它转换成内部装配配置。
    """

    enable_memory: bool = Field(default=False, description="是否启用记忆相关中间件")
    enable_planning: bool = Field(default=False, description="是否启用规划模式中间件和任务计划工具")
    enable_knowledge: bool = Field(default=False, description="是否启用知识库检索内部工具")


class AgentBuildConfig(BaseModel):
    """Agent 装配配置。

    这是 AgentService 解析 agent_id 模板并合并本次覆盖配置之后，
    传给 AgentAssembler 的内部装配配置。
    """

    system_prompt: str | None = Field(default=None, description="系统提示词")
    tool_names: list[str] = Field(default_factory=list, description="允许加载的工具名称")
    a2a: AgentA2AConfig | None = Field(default=None, description="A2A 装配配置")
    context_summarization: ContextSummarizationConfig | None = Field(default=None, description="模板会话上下文总结配置")
    features: AgentFeatureConfig = Field(default_factory=AgentFeatureConfig, description="Agent 内部装配能力开关")
