from uuid import uuid4

from app.server.agent.src.runtime.context import AgentRuntimeContext
from app.server.agent.src.runtime.context_schema import create_agent_context_schema
from app.server.agent.src.schemas.request import AgentRunRequest


class AgentRuntimeContextService:
    """Agent 运行上下文服务。

    RuntimeContext 是传给 LangChain create_agent(..., context_schema=...) 的运行时上下文数据。
    它不直接等同于 LangGraph state：
    - RuntimeContext 更像“本次调用的外部参数和系统变量”。
    - LangGraph state 更像“Agent 执行过程中由模型、工具、中间件共同维护的状态”。
    """

    def build_context(self, request: AgentRunRequest) -> AgentRuntimeContext:
        """根据运行请求构建 Agent 运行上下文。

        Args:
            request: 通用 Agent 运行请求。

        Returns:
            AgentRuntimeContext 运行上下文对象。
        """
        # thread_id 负责 LangGraph checkpoint 会话维度。
        # 如果调用方传入 conversation_id，Agent 会沿用该会话的 checkpoint 记忆；
        # 如果 conversation_id 为空，则生成临时 thread_id，适合 A2A 子 Agent 或一次性任务。
        thread_id = request.conversation_id or uuid4().hex

        # run_id 负责“单次 Agent 调用”维度。
        # 同一个 thread_id 可以有多次用户调用，checkpoint 会保留跨轮 state，
        # 所以检索结果这类临时 state 必须依赖 run_id 隔离，避免上一轮内容污染下一轮。
        run_id = uuid4().hex

        optional_features = request.optional_features.model_dump()

        # A2A 白名单只放进 runtime context，不放进模型用户消息。
        # 中间件会读取这个列表并注入可读说明，A2A 工具会读取这个列表做硬校验。
        a2a_sub_agent_list = request.a2a.sub_agent_list if request.a2a else []

        return AgentRuntimeContext(
            thread_id=thread_id,
            run_id=run_id,
            query=request.query,
            sys_var={"thread_id": thread_id, "run_id": run_id},
            user_var=request.inputs,
            inputs=request.inputs,
            file_ids=request.file_ids,
            allowed_tools=request.tools,
            optional_features=optional_features,
            memory_enabled=request.optional_features.long_term_memory_enabled,
            planning_enabled=request.optional_features.planning_enabled,
            knowledge_enabled=request.optional_features.knowledge_enabled,
            knowledge_base_ids=(request.knowledge.knowledge_base_ids if request.knowledge else []),
            a2a_sub_agent_list=a2a_sub_agent_list,
        )

    def get_context_schema(self):
        """获取 LangChain Agent 运行时上下文 schema。

        Returns:
            可传给 create_agent(context_schema=...) 的 Pydantic 模型类。
        """
        return create_agent_context_schema()
