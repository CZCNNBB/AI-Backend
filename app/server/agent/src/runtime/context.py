from typing import Any

from pydantic import BaseModel, Field


class AgentRuntimeContext(BaseModel):
    """Agent 单次运行上下文。

    Runtime context 描述本次调用的外部业务上下文。
    它不承载 agent_id、request_id 或调用方 metadata；追踪问题交给 LangSmith。
    """

    thread_id: str = Field(default="", description="会话线程 ID，优先来自 conversation_id")
    run_id: str = Field(default="", description="本次 Agent 调用 ID，用于隔离单次运行中的临时 state")
    query: str = Field(default="", description="本次运行的用户问题或任务指令")
    sys_var: dict[str, Any] = Field(default_factory=dict, description="系统变量，例如 thread_id")
    user_var: dict[str, Any] = Field(default_factory=dict, description="用户变量或编排层输入变量")
    inputs: dict[str, Any] = Field(default_factory=dict, description="业务输入变量")
    file_ids: list[str] = Field(default_factory=list, description="附件文件 ID 列表")
    allowed_tools: list[str] = Field(default_factory=list, description="本次运行允许调用的工具")
    optional_features: dict[str, Any] = Field(default_factory=dict, description="本次运行开启的增强能力")
    memory_enabled: bool = Field(default=False, description="本次运行是否启用长期记忆")
    planning_enabled: bool = Field(default=False, description="本次运行是否启用规划模式")
    knowledge_enabled: bool = Field(default=False, description="本次运行是否启用知识库检索")
    knowledge_base_ids: list[str] = Field(default_factory=list, description="本次运行允许访问的知识库 ID 白名单")
    a2a_sub_agent_list: list[str] = Field(default_factory=list, description="本次 A2A 可调用的子 Agent ID 列表")

    def to_langchain_context(self) -> dict[str, Any]:
        """转换为 LangChain Agent runtime context。

        Returns:
            可传给 LangChain agent.ainvoke(..., context=...) 的字典。
        """
        return self.model_dump()
