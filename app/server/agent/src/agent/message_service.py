import json
import logging
from typing import TYPE_CHECKING, AsyncIterator, Literal
from uuid import uuid4

from sqlmodel import Session

from app.common.db.postgres_db import postgres_transaction
from app.server.agent.src.runs import AgentRun, AgentRunService
from app.server.agent.src.schemas.request import (
    AgentMessageRequest,
    AgentResumeRequest,
    AgentRunRequest,
    AgentRuntimeCredentials,
)
from app.server.agent.src.schemas.response import AgentRunResponse
from app.server.platform.src.schemas import PlatformPrincipal
from app.server.platform.src.service import BusinessPlatformService

if TYPE_CHECKING:
    from app.server.agent.src.agent.service import AgentService

logger = logging.getLogger("ai_backend.agent.messages")

MessageRoute = tuple[Literal["run", "resume"], AgentRunRequest | AgentResumeRequest]


class AgentMessageService:
    """Agent 统一消息入口服务。

    该服务是正式对外 /agent/messages 接口背后的路由层：
    - 当前会话存在 interrupted run 时，把本次消息转换为 AgentResumeRequest。
    - 当前会话没有 interrupted run 时，把本次消息转换为 AgentRunRequest。

    这样前端只需要提交“用户消息”，不用关心底层是 run 还是 resume。
    """

    def __init__(
        self,
        *,
        agent_service: "AgentService",
        run_service: AgentRunService | None = None,
        platform_service: BusinessPlatformService | None = None,
    ):
        """初始化统一消息入口服务。

        Args:
            agent_service: 平台 Agent 服务，用于调用底层 run/resume 能力。
            run_service: Agent 运行记录服务，用于查询会话中待恢复的运行。
        """
        self.agent_service = agent_service
        self.run_service = run_service or AgentRunService()
        self.platform_service = platform_service or BusinessPlatformService()

    async def run_message(
        self,
        request: AgentMessageRequest,
        *,
        principal: PlatformPrincipal,
        business_authorization: str | None,
    ) -> AgentRunResponse:
        """处理非流式统一消息请求。

        Args:
            request: 统一消息请求。
        Returns:
            AgentRunResponse。新任务返回新 run_id；中断恢复返回原 run_id。
        """
        route_type, routed_request = self._route_message_with_short_session(
            request,
            principal=principal,
            business_authorization=business_authorization,
            stream=False,
        )
        if route_type == "resume":
            return await self.agent_service.resume(routed_request)
        return await self.agent_service.run(routed_request)

    async def stream_message(
        self,
        request: AgentMessageRequest,
        *,
        principal: PlatformPrincipal,
        business_authorization: str | None,
    ) -> AsyncIterator[dict[str, object]]:
        """处理流式统一消息请求。

        Args:
            request: 统一消息请求。
        Yields:
            标准化 Agent 流式事件。
        """
        route_type, routed_request = self._route_message_with_short_session(
            request,
            principal=principal,
            business_authorization=business_authorization,
            stream=True,
        )
        if route_type == "resume":
            async for event in self.agent_service.resume_stream(routed_request):
                yield event
            return

        async for event in self.agent_service.stream(routed_request):
            yield event

    def _route_message_with_short_session(
        self,
        request: AgentMessageRequest,
        *,
        principal: PlatformPrincipal,
        business_authorization: str | None,
        stream: bool,
    ) -> MessageRoute:
        """使用短事务判断本次消息应创建新运行还是恢复中断运行。

        Args:
            request: 统一消息请求。
            stream: 是否流式返回。

        Returns:
            二元组：(run/resume, 对应的底层请求对象)。
        """
        # 路由阶段只查询一次 agent_runs。必须在 with 块内完成请求对象构建，
        # 避免把仍绑定 Session 的 ORM 对象带到后续 SSE 生成器中。
        with postgres_transaction() as route_db:
            return self._route_message(
                request,
                route_db,
                principal=principal,
                business_authorization=business_authorization,
                stream=stream,
            )

    def _route_message(
        self,
        request: AgentMessageRequest,
        db: Session,
        *,
        principal: PlatformPrincipal,
        business_authorization: str | None,
        stream: bool,
    ) -> MessageRoute:
        """判断统一消息应该创建新运行还是恢复中断运行。

        Args:
            request: 统一消息请求。
            db: PostgreSQL Session。
            stream: 是否流式返回。

        Returns:
            二元组：(run/resume, 对应的底层请求对象)。
        """
        self.platform_service.require_agent_binding(
            db,
            agent_id=request.agent_id,
            platform_id=principal.platform_id,
        )
        pending_run = self._find_pending_interrupted_run(request, db, principal=principal)
        if pending_run is not None:
            resume_request = self._build_resume_request(
                request,
                pending_run,
                principal=principal,
                business_authorization=business_authorization,
                stream=stream,
            )
            return "resume", resume_request

        run_request = self._build_run_request(
            request,
            principal=principal,
            business_authorization=business_authorization,
            stream=stream,
        )
        logger.info(
            "统一消息入口路由到新运行: conversation_id=%s agent_id=%s message_type=%s stream=%s",
            request.conversation_id,
            request.agent_id,
            request.message_type,
            stream,
        )
        return "run", run_request

    def _find_pending_interrupted_run(
        self,
        request: AgentMessageRequest,
        db: Session,
        *,
        principal: PlatformPrincipal,
    ) -> AgentRun | None:
        """根据 conversation_id 查询是否存在待恢复运行。

        Args:
            request: 统一消息请求。
            db: PostgreSQL Session。

        Returns:
            interrupted 状态的 AgentRun；没有 conversation_id 或不存在中断时返回 None。
        """
        if not request.conversation_id:
            return None
        return self.run_service.get_latest_interrupted_by_conversation(
            db,
            platform_id=principal.platform_id,
            external_user_id=request.external_user_id,
            conversation_id=request.conversation_id,
        )

    def _build_run_request(
        self,
        request: AgentMessageRequest,
        *,
        principal: PlatformPrincipal,
        business_authorization: str | None,
        stream: bool,
    ) -> AgentRunRequest:
        """把统一消息请求转换为普通 Agent 运行请求。

        Args:
            request: 统一消息请求。
            stream: 是否流式返回。

        Returns:
            AgentRunRequest。
        """
        conversation_id = request.conversation_id or f"conv_{uuid4().hex}"
        return AgentRunRequest(
            agent_id=request.agent_id,
            platform_id=principal.platform_id,
            external_user_id=request.external_user_id,
            runtime_credentials=AgentRuntimeCredentials(business_token=business_authorization),
            query=self._build_query_text(request),
            conversation_id=conversation_id,
            stream=stream,
            system_prompt=request.system_prompt,
            inputs=self._build_run_inputs(request),
            file_ids=request.file_ids,
            tools=request.tools,
            optional_features=request.optional_features,
            knowledge=request.knowledge,
            a2a=request.a2a,
            runtime_options=request.runtime_options,
        )

    def _build_resume_request(
        self,
        request: AgentMessageRequest,
        pending_run: AgentRun,
        *,
        principal: PlatformPrincipal,
        business_authorization: str | None,
        stream: bool,
    ) -> AgentResumeRequest:
        """把统一消息请求转换为中断恢复请求。

        Args:
            request: 统一消息请求。
            pending_run: 当前会话中最新的 interrupted run。
            stream: 是否流式返回。

        Returns:
            AgentResumeRequest。
        """
        conversation_id = pending_run.conversation_id or request.conversation_id
        if not conversation_id:
            raise RuntimeError("中断恢复缺少 conversation_id/thread_id")
        checkpoint_thread_id = (
            f"platform:{principal.platform_id}:"
            f"user:{request.external_user_id}:"
            f"conversation:{conversation_id}"
        )

        return AgentResumeRequest(
            run_id=pending_run.run_id,
            conversation_id=conversation_id,
            thread_id=checkpoint_thread_id,
            platform_id=principal.platform_id,
            external_user_id=request.external_user_id,
            runtime_credentials=AgentRuntimeCredentials(business_token=business_authorization),
            resume_value=self._build_resume_value(request, pending_run),
            stream=stream,
        )

    def _build_resume_value(self, request: AgentMessageRequest, pending_run: AgentRun) -> dict[str, object]:
        """根据消息 payload 和中断记录构建标准 resume_value。

        Args:
            request: 统一消息请求。
            pending_run: 当前待恢复运行，用于兜底读取 interrupt_type。

        Returns:
            固定格式 {type: string, data: object}。
        """
        payload = request.payload
        metadata = dict(pending_run.extra_metadata or {})
        interrupt_type = str(payload.get("type") or metadata.get("interrupt_type") or "unknown").strip() or "unknown"

        data = self._extract_payload_data(payload)
        if request.message:
            data.setdefault("message", request.message)
        data.setdefault("message_type", request.message_type)

        return {"type": interrupt_type, "data": data}

    def _extract_payload_data(self, payload: dict[str, object]) -> dict[str, object]:
        """从统一消息 payload 中提取业务 data。

        Args:
            payload: 前端传入的结构化负载。

        Returns:
            业务数据字典。payload 已包含 data 时优先使用 data，否则把除 type 外的字段整体作为 data。
        """
        data = payload.get("data")
        if isinstance(data, dict):
            return dict(data)
        if payload:
            # 表单提交时如果前端没有包 data，就把整个 payload 当作 data，避免丢字段。
            return {key: value for key, value in payload.items() if key != "type"}
        return {}

    def _build_run_inputs(self, request: AgentMessageRequest) -> dict[str, object]:
        """构建新运行的 inputs，保留统一消息的结构化上下文。

        Args:
            request: 统一消息请求。

        Returns:
            合并后的 inputs。保留原 inputs，并额外注入 message_type 和 message_payload。
        """
        inputs: dict[str, object] = dict(request.inputs)
        inputs.setdefault("message_type", request.message_type)
        if request.payload:
            inputs.setdefault("message_payload", request.payload)
        return inputs

    def _build_query_text(self, request: AgentMessageRequest) -> str:
        """构建新任务运行时传给 Agent 的 query 文本。

        Args:
            request: 统一消息请求。

        Returns:
            非空 query 文本。

        Raises:
            RuntimeError: 文本和结构化负载都为空时抛出。
        """
        if request.message:
            return request.message
        if request.payload:
            payload_text = json.dumps(request.payload, ensure_ascii=False)
            return f"用户提交了一条 {request.message_type} 类型的结构化消息：{payload_text}"
        raise RuntimeError("message 和 payload 不能同时为空")
