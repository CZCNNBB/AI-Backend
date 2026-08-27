import logging
from typing import Any

from sqlmodel import Session

from app.server.agent.src.context import AgentContextService
from app.server.agent.src.memory import AgentMemoryService
from app.server.agent.src.runtime import AgentRuntimeContext, AgentRuntimeContextService
from app.server.agent.src.runs import AgentRunService
from app.server.agent.src.schemas.request import AgentRunRequest, ModelRuntimeOptions
from app.server.agent.src.templates.schemas import AgentTemplateConfig
from app.server.agent.src.templates.service import AgentTemplateService

logger = logging.getLogger("ai_backend.agent.lifecycle")


class AgentRunLifecycleService:
    """Agent 单次运行生命周期服务。

    该服务负责 run/stream 共用的前置和后置流程：
    - 根据 agent_id 合并模板配置。
    - 构建运行上下文。
    - 写入用户可见历史会话中的用户消息。
    - 创建和更新 agent_runs 运行记录。
    - 写入用户可见历史会话中的助手消息。

    注意：用户可见历史会话由 `agent_conversations` / `agent_messages` 承载；
    长期记忆是另一个预留能力，不应和这里的历史会话写入混为一谈。
    """

    def __init__(
        self,
        *,
        runtime_context_service: AgentRuntimeContextService | None = None,
        memory_service: AgentMemoryService | None = None,
        context_service: AgentContextService | None = None,
        run_service: AgentRunService | None = None,
        template_service: AgentTemplateService | None = None,
    ):
        """初始化 Agent 运行生命周期服务。

        Args:
            runtime_context_service: 运行时上下文服务，负责构建 thread_id、run_id 等。
            memory_service: 长期记忆预留服务，当前不负责用户可见历史会话。
            context_service: 历史会话服务，负责读写 agent_conversations 和 agent_messages。
            run_service: Agent 运行记录服务，负责读写 agent_runs。
            template_service: Agent 模板服务，负责按 agent_id 加载模板配置。
        """
        self.runtime_context_service = runtime_context_service or AgentRuntimeContextService()
        self.memory_service = memory_service or AgentMemoryService()
        self.context_service = context_service or AgentContextService()
        self.run_service = run_service or AgentRunService()
        self.template_service = template_service or AgentTemplateService()

    def build_conversation_title(self, query: str) -> str:
        """根据用户第一条问题生成会话标题。

        Args:
            query: 用户本轮输入文本。

        Returns:
            清理空白并截断到数据库 title 字段长度以内的标题；输入为空时返回“新会话”。
        """
        # 会话标题用于前端展示，不参与 Agent 推理；这里只做轻量清洗，避免过度加工用户原话。
        title = " ".join((query or "").split())
        if not title:
            return "新会话"
        return title[:255]

    def resolve_template_request(self, request: AgentRunRequest, db: Session | None) -> AgentRunRequest:
        """根据 agent_id 加载模板配置，并按“模板优先”规则合并本次请求。

        Args:
            request: API 或内部调用传入的原始运行请求。
            db: PostgreSQL Session；API 调用场景会传入，A2A 等内部场景可能为空。

        Returns:
            合并模板后的 AgentRunRequest；未传 agent_id 时原样返回。
        """
        if not request.agent_id:
            # 会话总结只能由 Agent 模板配置启用，不能通过普通运行请求临时挂载。
            return request.model_copy(update={"context_summarization": None}, deep=True)

        template_config = self.load_template_config(request.agent_id, db)
        update_data = {
            # 传入 agent_id 后，模板中的核心装配配置拥有最高优先级。
            # 请求体里的 system_prompt=""、tools=[] 只表示前端表单默认值，不能覆盖模板。
            "system_prompt": template_config.system_prompt or request.system_prompt,
            "tools": list(template_config.tools or request.tools or []),
            "optional_features": template_config.optional_features or request.optional_features,
            "a2a": template_config.a2a if template_config.a2a is not None else request.a2a,
            # 会话总结只接受模板配置，不允许请求体覆盖。
            "context_summarization": template_config.context_summarization,
            "runtime_options": self.resolve_template_runtime_options(
                template_config.runtime_options,
                request.runtime_options,
            ),
        }
        return request.model_copy(update=update_data, deep=True)

    def load_template_config(self, agent_id: str, db: Session | None) -> AgentTemplateConfig:
        """按 agent_id 查询启用中的 Agent 模板配置。

        Args:
            agent_id: Agent 模板 ID。
            db: PostgreSQL Session；为空时临时打开只读会话。

        Returns:
            AgentTemplateConfig 模板配置。
        """
        if db is not None:
            template = self.template_service.get_template(db, agent_id)
        else:
            from app.common.db.postgres_db import get_db_session

            with get_db_session() as inner_db:
                template = self.template_service.get_template(inner_db, agent_id)

        if template is None:
            raise RuntimeError(f"Agent 模板不存在: {agent_id}")
        if template.status != "active":
            raise RuntimeError(f"Agent 模板未启用: {agent_id}")
        return template.config

    def resolve_template_runtime_options(
        self,
        template_options: ModelRuntimeOptions,
        request_options: ModelRuntimeOptions,
    ) -> ModelRuntimeOptions:
        """按“模板优先”规则确定模型运行参数。

        Args:
            template_options: 模板默认模型运行参数。
            request_options: 本次请求传入的模型运行参数。

        Returns:
            合并后的模型运行参数；模板缺少 model_code 时才使用请求体兜底。
        """
        # 模型选择属于 Agent 模板的核心能力配置，不能被请求体中的空值或临时字段覆盖。
        # 只有模板没有绑定模型时，才允许使用请求体里的 model_code 作为兜底，便于临时模板测试。
        merged = template_options.model_dump(mode="python")
        if not merged.get("model_code") and request_options.model_code:
            merged["model_code"] = request_options.model_code
        return ModelRuntimeOptions(**merged)

    def prepare_run_context(
        self,
        request: AgentRunRequest,
        db: Session | None,
    ) -> tuple[AgentRuntimeContext, bool, bool]:
        """构建运行上下文，并写入用户消息和主运行记录。

        这是 run() 和 stream() 的公共前置步骤。
        普通 API 调用会传入 db，因此会记录 agent_runs；A2A 子 Agent 调用会传 db=None，
        子 Agent 的运行记录由 a2a_call 工具提前写入 agent_runs(run_type=sub)。

        Args:
            request: Agent 运行请求。
            db: PostgreSQL Session。

        Returns:
            (运行上下文, 是否启用持久会话记录, 是否写入主运行记录)。
        """
        context = self.runtime_context_service.build_context(request)
        context_enabled = request.conversation_id is not None and db is not None
        run_record_enabled = db is not None
        user_message_id: str | None = None

        if db is not None and (request.platform_id is None or not request.external_user_id):
            raise RuntimeError("持久化 Agent 运行缺少 platform_id 或 external_user_id")

        if context_enabled:
            self.context_service.ensure_conversation(
                db,
                platform_id=request.platform_id,
                external_user_id=request.external_user_id,
                conversation_id=context.thread_id,
                title=self.build_conversation_title(request.query),
                metadata={},
            )
            user_message = self.context_service.add_user_message(
                db,
                conversation_id=context.thread_id,
                content=request.query,
                metadata={"run_id": context.run_id},
            )
            user_message_id = user_message.message_id

        if run_record_enabled:
            self.run_service.create_running(
                db,
                run_id=context.run_id,
                platform_id=request.platform_id,
                external_user_id=request.external_user_id,
                run_type="main",
                conversation_id=context.thread_id if request.conversation_id else None,
                user_message_id=user_message_id,
                query=request.query,
                agent_id=request.agent_id,
                metadata={
                    "agent_id": request.agent_id,
                    "system_prompt": request.system_prompt,
                    "tools": request.tools,
                    "optional_features": request.optional_features.model_dump(mode="python"),
                    "knowledge": request.knowledge.model_dump(mode="python") if request.knowledge else None,
                    "a2a": request.a2a.model_dump(mode="python") if request.a2a else None,
                    "a2a_sub_agent_list": request.a2a.sub_agent_list if request.a2a else [],
                    "context_summarization": (
                        request.context_summarization.model_dump(mode="python")
                        if request.context_summarization
                        else None
                    ),
                    "runtime_options": request.runtime_options.model_dump(mode="python"),
                    "model_code": request.runtime_options.model_code,
                },
            )
        logger.info(
            "Agent 运行开始: run_id=%s thread_id=%s query_length=%d persistent_conversation=%s "
            "stream=%s conversation_id_present=%s",
            context.run_id,
            context.thread_id,
            len(request.query),
            request.conversation_id is not None,
            request.stream,
            request.conversation_id is not None,
        )

        return context, context_enabled, run_record_enabled

    async def finalize_run(
        self,
        context: AgentRuntimeContext,
        answer: str,
        context_enabled: bool,
        run_record_enabled: bool,
        db: Session | None,
        elapsed_ms: float,
    ) -> None:
        """写入用户可见历史会话，并把主运行记录标记为成功。

        Args:
            context: Agent 运行上下文。
            answer: Agent 最终文本回答。
            context_enabled: 是否启用持久会话记录。
            run_record_enabled: 是否启用主运行记录。
            db: PostgreSQL Session。
            elapsed_ms: 本次运行总耗时，单位毫秒。
        """
        # 长期记忆当前仍是预留能力；真实的用户可见历史会话由 ContextService 写入 agent_messages。
        await self.memory_service.save_interaction(context, answer)

        assistant_message_id: str | None = None
        if context_enabled:
            assistant_message = self.context_service.add_assistant_message(
                db,
                conversation_id=context.thread_id,
                content=answer,
                metadata={"run_id": context.run_id},
            )
            assistant_message_id = assistant_message.message_id

        if run_record_enabled and db is not None:
            self.run_service.mark_success(
                db,
                run_id=context.run_id,
                answer=answer,
                assistant_message_id=assistant_message_id,
                elapsed_ms=elapsed_ms,
            )

    def mark_run_failed(
        self,
        context: AgentRuntimeContext,
        run_record_enabled: bool,
        db: Session | None,
        error: Exception,
        elapsed_ms: float,
    ) -> None:
        """把主运行记录标记为失败。

        Args:
            context: Agent 运行上下文。
            run_record_enabled: 是否启用主运行记录。
            db: PostgreSQL Session。
            error: 运行过程中捕获到的异常。
            elapsed_ms: 失败前耗时，单位毫秒。
        """
        if run_record_enabled and db is not None:
            self.run_service.mark_failed(
                db,
                run_id=context.run_id,
                error_message=str(error),
                elapsed_ms=elapsed_ms,
            )
