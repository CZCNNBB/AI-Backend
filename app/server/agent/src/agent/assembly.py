from dataclasses import dataclass
from typing import Any

from app.server.agent.src.runtime.context import AgentRuntimeContext


@dataclass
class AgentAssembly:
    """Agent 装配结果。

    这个对象不是对外 API 响应，而是 AgentService 内部的“装配产物快照”。
    后续调试 agent 组装问题时，可以通过它看到模型、工具、提示词、
    上下文 schema、中间件等是否按预期被装配进来。
    """

    # LangChain create_agent(...) 返回的 agent 实例。
    agent: Any

    # 本次装配使用的模型实例。
    model: Any

    # 本次允许 agent 使用的工具列表。
    tools: list[Any]

    # 渲染后的系统提示词。
    system_prompt: str

    # 传给 LangChain create_agent(context_schema=...) 的运行时上下文结构。
    context_schema: Any

    # 传给 LangChain create_agent(middleware=...) 的中间件实例列表。
    middlewares: list[Any]

    # 本次运行的业务上下文，包括 sys_var、user_var、inputs 等。
    context: AgentRuntimeContext

    # 装配过程产生的内部信息，不直接作为 /agent/run 的响应字段返回。
    metadata: dict[str, Any]
