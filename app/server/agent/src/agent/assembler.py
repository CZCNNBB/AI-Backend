import logging
import time

from langchain.agents import create_agent
from sqlmodel import Session

from app.server.agent.src.agent.assembly import AgentAssembly
from app.server.agent.src.checkpoint import AgentCheckpointService
from app.server.agent.src.middlewares import MiddlewareFactory
from app.server.agent.src.model import AgentModelService
from app.server.agent.src.prompts import DEFAULT_AGENT_SYSTEM_PROMPT, AgentPromptService
from app.server.agent.src.runtime import AgentRuntimeContext, AgentRuntimeContextService
from app.server.agent.src.schemas.config import AgentBuildConfig, AgentFeatureConfig
from app.server.agent.src.schemas.request import AgentRunRequest
from app.server.agent.src.tools import AgentToolService


logger = logging.getLogger("ai_backend.agent.assembler")


class AgentAssembler:
    """Agent 组装器，负责完整的 Agent 装配流程。

    组装流程是一个不可拆分的整体：
    构建配置 → 渲染提示词 → 加载工具 → 构建上下文 schema →
    创建中间件 → 创建模型 → 获取 checkpointer → 调用 create_agent()。

    所有步骤按顺序执行，不暴露中间产物，外部只需传入请求和上下文即可获得
    完整的 AgentAssembly。
    """

    def __init__(
        self,
        *,
        model_service: AgentModelService | None = None,
        tool_service: AgentToolService | None = None,
        prompt_service: AgentPromptService | None = None,
        runtime_context_service: AgentRuntimeContextService | None = None,
        middleware_factory: MiddlewareFactory | None = None,
        checkpoint_service: AgentCheckpointService | None = None,
    ):
        """初始化 Agent 组装器。

        Args:
            model_service: 模型服务，负责创建 ChatOpenAI 等模型实例。
            tool_service: 工具服务，负责按工具名筛选本次可用工具。
            prompt_service: Prompt 服务，负责渲染系统提示词。
            runtime_context_service: 运行时上下文服务，负责构建 context schema。
            middleware_factory: 中间件工厂，负责返回本次需要装配的中间件。
            checkpoint_service: Checkpointer 服务，负责 LangGraph 状态持久化。
        """
        self.model_service = model_service or AgentModelService()
        self.tool_service = tool_service or AgentToolService()
        self.prompt_service = prompt_service or AgentPromptService()
        self.runtime_context_service = runtime_context_service or AgentRuntimeContextService()
        self.middleware_factory = middleware_factory or MiddlewareFactory()
        self.checkpoint_service = checkpoint_service or AgentCheckpointService()

    async def assemble(
        self,
        request: AgentRunRequest,
        context: AgentRuntimeContext,
        db: Session | None = None,
    ) -> AgentAssembly:
        """执行完整的 Agent 组装流程。

        Args:
            request: 通用 Agent 运行请求，包含模型参数、工具白名单、提示词等。
            context: Agent 运行上下文，包含 thread_id、inputs 等业务变量。

        Returns:
            AgentAssembly，包含已组装的 agent、model、tools、middlewares 和调试元数据。
        """
        assembly_started_at = time.perf_counter()
        logger.info(
            "Agent 组装开始: thread_id=%s model_code=%s tools=%s",
            context.thread_id,
            request.runtime_options.model_code,
            request.tools,
        )

        # 第一步：从请求中直接构建内部装配配置（不再通过中间方法包装）。
        features = AgentFeatureConfig(
            enable_memory=request.optional_features.long_term_memory_enabled,
            enable_planning=request.optional_features.planning_enabled,
            enable_knowledge=request.optional_features.knowledge_enabled,
        )
        build_config = AgentBuildConfig(
            system_prompt=request.system_prompt or DEFAULT_AGENT_SYSTEM_PROMPT,
            tool_names=request.tools,
            a2a=request.a2a,
            context_summarization=request.context_summarization,
            features=features,
        )
        logger.info(
            "Agent 构建配置就绪: thread_id=%s memory=%s planning=%s knowledge=%s",
            context.thread_id,
            features.enable_memory,
            features.enable_planning,
            features.enable_knowledge,
        )

        # 第二步：渲染系统提示词。
        system_prompt = self.prompt_service.render_system_prompt(
            build_config.system_prompt or DEFAULT_AGENT_SYSTEM_PROMPT,
            context.inputs,
        )
        logger.info(
            "系统提示词渲染完成: thread_id=%s prompt_length=%d input_keys=%s",
            context.thread_id,
            len(system_prompt),
            sorted(context.inputs.keys()),
        )

        # 第三步：按工具白名单加载本次可用工具。
        # 复制工具列表，避免动态追加内置工具时污染 ToolService 的缓存对象。
        tools = list(await self.tool_service.get_tools(build_config.tool_names, db=db))
        logger.info(
            "工具加载完成: thread_id=%s requested=%d loaded=%d names=%s",
            context.thread_id,
            len(build_config.tool_names),
            len(tools),
            [getattr(tool, "name", tool.__class__.__name__) for tool in tools],
        )

        # 第三步附加：规划工具动态注入。
        # planning_enabled 是能力开关，开启后自动给 Agent 装配任务计划工具，避免前端重复维护 tools 白名单。
        if features.enable_planning:
            from app.server.agent.src.tools.planning_tools import set_task_plan, update_task_step

            existing_tool_names = {getattr(tool, "name", tool.__class__.__name__) for tool in tools}
            for planning_tool in [set_task_plan, update_task_step]:
                if getattr(planning_tool, "name", "") not in existing_tool_names:
                    tools.append(planning_tool)

        # 第三步附加：附件工具动态注入。
        # file_ids 非空表示本轮有可访问附件；读取和关键词定位工具都由系统自动装配。
        if request.file_ids:
            from app.server.agent.src.tools.file_tools import read_uploaded_file, search_uploaded_files

            existing_tool_names = {getattr(tool, "name", tool.__class__.__name__) for tool in tools}
            for file_tool in [read_uploaded_file, search_uploaded_files]:
                if getattr(file_tool, "name", "") not in existing_tool_names:
                    tools.append(file_tool)

        # 第三步附加：知识库检索工具动态注入。
        # 模板负责声明能力，本次调用的 knowledge 参数负责提供访问白名单；二者同时满足才装配。
        if features.enable_knowledge and context.knowledge_base_ids:
            from app.server.agent.src.tools.knowledge_tools import search_knowledge_base

            existing_tool_names = {getattr(tool, "name", tool.__class__.__name__) for tool in tools}
            if search_knowledge_base.name not in existing_tool_names:
                tools.append(search_knowledge_base)

        # 第三步附加：A2A 工具动态注入。仅 a2a.sub_agent_list 非空时装配 a2a_call 工具。
        # 子 Agent 元信息查询和 system prompt 注入由 A2AAgentContextMiddleware 负责。
        if build_config.a2a and build_config.a2a.sub_agent_list:
            from app.server.agent.src.tools.a2a_tool import a2a_call
            tools.append(a2a_call)

        # 第四步：创建主聊天模型。
        model = self.model_service.create_chat_model(
            db=db,
            model_code=request.runtime_options.model_code,
            temperature=request.runtime_options.temperature,
            timeout_seconds=request.runtime_options.timeout_seconds,
            max_retries=request.runtime_options.max_retries,
        )

        # 模板存在会话总结配置且本次为持久化会话时，创建独立总结模型。
        # 无 conversation_id 的 A2A 或一次性调用没有跨轮上下文，不装配会话总结。
        summary_model = None
        if build_config.context_summarization is not None and request.conversation_id:
            summary_model = self.model_service.create_chat_model(
                db=db,
                model_code=build_config.context_summarization.model_code,
                temperature=0,
                timeout_seconds=request.runtime_options.timeout_seconds,
                max_retries=request.runtime_options.max_retries,
            )
            logger.info(
                "会话总结模型已就绪: thread_id=%s model_code=%s",
                context.thread_id,
                build_config.context_summarization.model_code,
            )
        elif build_config.context_summarization is not None:
            logger.info("会话总结已跳过: thread_id=%s reason=empty_conversation_id", context.thread_id)

        # 第五步：构建 LangChain runtime context schema。
        context_schema = self.runtime_context_service.get_context_schema()

        # 第六步：创建中间件实例，并提取中间件声明的 LangGraph state schema。
        middlewares = self.middleware_factory.build_langchain_middlewares(
            features,
            summary_model=summary_model,
            context_summarization=build_config.context_summarization if summary_model is not None else None,
        )
        middleware_names = self.middleware_factory.describe_middlewares(
            features,
            context_summarization_enabled=summary_model is not None,
        )
        state_schema_names = self.middleware_factory.describe_state_schemas(middlewares)
        logger.info(
            "中间件装配完成: thread_id=%s middlewares=%s state_schemas=%s",
            context.thread_id,
            middleware_names,
            state_schema_names,
        )

        # 第七步：获取 LangGraph checkpointer。
        # 现在 conversation_id 是唯一的会话记忆开关：
        # - 有 conversation_id：启用 PostgreSQL checkpointer，保留跨轮 Agent 状态。
        # - 无 conversation_id：视为一次性任务或 A2A 子 Agent 调用，不挂 checkpointer。
        if request.conversation_id:
            checkpointer = await self.checkpoint_service.get_checkpointer()
            logger.info(
                "Checkpointer 已就绪: thread_id=%s enabled=%s",
                context.thread_id,
                checkpointer is not None,
            )
        else:
            checkpointer = None
            logger.info(
                "Checkpointer 已跳过: thread_id=%s reason=empty_conversation_id",
                context.thread_id,
            )

        # 第八步：真正创建 LangChain Agent。
        agent = create_agent(
            model=model,
            tools=tools,
            system_prompt=system_prompt,
            context_schema=context_schema,
            middleware=middlewares,
            checkpointer=checkpointer,
        )
        logger.info(
            "Agent 组装完成: thread_id=%s elapsed_ms=%.2f",
            context.thread_id,
            (time.perf_counter() - assembly_started_at) * 1000,
        )

        return AgentAssembly(
            agent=agent,
            model=model,
            tools=tools,
            system_prompt=system_prompt,
            context_schema=context_schema,
            middlewares=middlewares,
            context=context,
            metadata={
                "model_code": request.runtime_options.model_code,
                "context_summarization_model_code": (
                    build_config.context_summarization.model_code
                    if summary_model is not None and build_config.context_summarization is not None
                    else None
                ),
                "tool_count": len(tools),
                "tools": [getattr(tool, "name", tool.__class__.__name__) for tool in tools],
                "middlewares": middleware_names,
                "context_schema": context_schema.__name__,
                "state_schemas": state_schema_names,
                "checkpointer_enabled": checkpointer is not None,
                "conversation_id_present": request.conversation_id is not None,
            },
        )


