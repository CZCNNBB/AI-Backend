from typing import Any

from pydantic import BaseModel, Field, create_model


def create_agent_context_schema() -> type[BaseModel]:
    """创建 LangChain Agent 使用的运行时上下文 schema。

    Returns:
        可传入 create_agent(context_schema=...) 的 Pydantic 模型类。
    """
    return create_model(
        "DynamicAgentRuntimeContext",
        __base__=BaseModel,
        thread_id=(str, Field(default="", description="会话线程 ID")),
        run_id=(str, Field(default="", description="本次 Agent 调用 ID")),
        query=(str, Field(default="", description="本次运行任务")),
        sys_var=(dict[str, Any], Field(default_factory=dict, description="系统变量")),
        user_var=(dict[str, Any], Field(default_factory=dict, description="用户变量")),
        inputs=(dict[str, Any], Field(default_factory=dict, description="业务输入变量")),
        file_ids=(list[str], Field(default_factory=list, description="附件文件 ID 列表")),
        allowed_tools=(list[str], Field(default_factory=list, description="允许调用的工具")),
        optional_features=(dict[str, Any], Field(default_factory=dict, description="本次运行开启的增强能力")),
        memory_enabled=(bool, Field(default=False, description="是否启用长期记忆")),
        planning_enabled=(bool, Field(default=False, description="是否启用规划模式")),
        knowledge_enabled=(bool, Field(default=False, description="是否启用知识库检索")),
        knowledge_base_ids=(list[str], Field(default_factory=list, description="允许访问的知识库 ID 白名单")),
        a2a_sub_agent_list=(list[str], Field(default_factory=list, description="本次 A2A 允许调用的子 Agent ID 列表")),
    )
