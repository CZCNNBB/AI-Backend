import logging
import time
from typing import Any, AsyncIterator

from langgraph.types import Command
from sqlmodel import Session

from app.common.db.postgres_db import postgres_transaction
from app.server.agent.src.agent.assembler import AgentAssembler
from app.server.agent.src.agent.streaming import AgentStreamEventParser
from app.server.agent.src.context import AgentContextService
from app.server.agent.src.memory import AgentMemoryService
from app.server.agent.src.runtime import AgentRuntimeContext
from app.server.agent.src.runs import AgentRunService
from app.server.agent.src.schemas.request import (
    AgentA2AConfig,
    AgentKnowledgeConfig,
    AgentOptionalFeatures,
    AgentResumeRequest,
    AgentRunRequest,
    ModelRuntimeOptions,
)
from app.server.agent.src.schemas.response import AgentRunResponse
from app.server.agent.src.config import get_agent_runtime_settings

logger = logging.getLogger("ai_backend.agent.resume")


class AgentResumeService:
    """Agent 中断恢复服务。

    该服务只负责 `/agent/resume` 相关流程：
    - 校验被中断的 agent_runs 记录。
    - 根据运行记录中的 metadata 重建 Agent 装配请求。
    - 使用 LangGraph `Command(resume=...)` 恢复 checkpoint 中的图执行。
    - 把恢复后的状态写回 agent_runs 和用户可见会话记录。
    """

    def __init__(
        self,
        *,
        assembler: AgentAssembler,
        memory_service: AgentMemoryService | None = None,
        context_service: AgentContextService | None = None,
        run_service: AgentRunService | None = None,
        stream_parser: AgentStreamEventParser | None = None,
    ):
        """初始化中断恢复服务。

        Args:
            assembler: Agent 组装器，必须和主 AgentService 共用同一个实例。
            memory_service: 长期记忆预留服务，当前不负责用户可见历史会话。
            context_service: 历史会话服务，负责写入恢复后的用户可见助手消息。
            run_service: Agent 运行记录服务，负责更新 agent_runs 状态。
            stream_parser: 流式事件解析器，负责解析 messages/updates 分片。
        """
        self.assembler = assembler
        self.memory_service = memory_service or AgentMemoryService()
        self.context_service = context_service or AgentContextService()
        self.run_service = run_service or AgentRunService()
        self.stream_parser = stream_parser or AgentStreamEventParser()

    def _build_resume_request_from_run(
        self,
        run_row: Any,
        resume_request: AgentResumeRequest,
    ) -> AgentRunRequest:
        """根据被中断的运行记录重建 AgentRunRequest。

        Args:
            run_row: agent_runs 表中的原始运行记录。
            resume_request: 前端传入的恢复请求。

        Returns:
            可用于重新组装同一个 Agent 的 AgentRunRequest。
        """
        metadata = dict(getattr(run_row, "extra_metadata", None) or {})
        runtime_options_data = metadata.get("runtime_options") or {}
        if not runtime_options_data and metadata.get("model_code"):
            runtime_options_data = {"model_code": metadata.get("model_code")}

        optional_features_data = metadata.get("optional_features") or {}
        a2a_data = metadata.get("a2a")
        if a2a_data is None and metadata.get("a2a_sub_agent_list"):
            a2a_data = {"sub_agent_list": metadata.get("a2a_sub_agent_list") or []}

        # 注意：resume 使用中断时保存的已解析配置，不再重新读取模板覆盖。
        # 这样即使用户在中断期间修改了 Agent 模板，也不会影响当前 checkpoint 的恢复。
        return AgentRunRequest(
            agent_id=getattr(run_row, "agent_id", None) or metadata.get("agent_id"),
            query=getattr(run_row, "query", None) or "继续执行中断任务",
            conversation_id=resume_request.thread_id,
            stream=resume_request.stream,
            system_prompt=metadata.get("system_prompt"),
            inputs={},
            file_ids=[],
            tools=list(metadata.get("tools") or []),
            optional_features=AgentOptionalFeatures(**optional_features_data),
            knowledge=(
                AgentKnowledgeConfig(**metadata["knowledge"])
                if isinstance(metadata.get("knowledge"), dict)
                else None
            ),
            a2a=AgentA2AConfig(**a2a_data) if isinstance(a2a_data, dict) else None,
            context_summarization=metadata.get("context_summarization"),
            runtime_options=ModelRuntimeOptions(**runtime_options_data),
        )

    def _build_resume_context(
        self,
        run_row: Any,
        resume_request: AgentResumeRequest,
        resolved_request: AgentRunRequest,
    ) -> AgentRuntimeContext:
        """构建恢复执行使用的运行上下文。

        Args:
            run_row: 被中断的运行记录。
            resume_request: 前端传入的恢复请求。
            resolved_request: 已根据运行记录恢复出的请求参数。

        Returns:
            使用原 run_id 和 thread_id 的 AgentRuntimeContext。
        """
        a2a_sub_agent_list = resolved_request.a2a.sub_agent_list if resolved_request.a2a else []
        return AgentRuntimeContext(
            thread_id=resume_request.thread_id,
            run_id=resume_request.run_id,
            query=getattr(run_row, "query", None) or resolved_request.query,
            sys_var={"thread_id": resume_request.thread_id, "run_id": resume_request.run_id},
            user_var=resolved_request.inputs,
            inputs=resolved_request.inputs,
            file_ids=resolved_request.file_ids,
            allowed_tools=resolved_request.tools,
            optional_features=resolved_request.optional_features.model_dump(mode="python"),
            memory_enabled=resolved_request.optional_features.long_term_memory_enabled,
            planning_enabled=resolved_request.optional_features.planning_enabled,
            knowledge_enabled=resolved_request.optional_features.knowledge_enabled,
            knowledge_base_ids=(
                resolved_request.knowledge.knowledge_base_ids
                if resolved_request.knowledge
                else []
            ),
            a2a_sub_agent_list=a2a_sub_agent_list,
        )

    def _get_interrupted_run(self, db: Session, resume_request: AgentResumeRequest) -> Any:
        """查询并校验待恢复的中断运行记录。

        Args:
            db: PostgreSQL Session。
            resume_request: 前端传入的恢复请求。

        Returns:
            agent_runs 表中的运行记录。

        Raises:
            RuntimeError: 运行不存在、状态不正确或 thread_id 不匹配时抛出。
        """
        run_row = self.run_service.get_by_run_id(db, resume_request.run_id)
        if run_row is None:
            raise RuntimeError(f"Agent 运行记录不存在: {resume_request.run_id}")
        if run_row.status != "interrupted":
            raise RuntimeError(f"Agent 运行状态不是 interrupted，当前状态: {run_row.status}")
        if run_row.conversation_id and run_row.conversation_id != resume_request.thread_id:
            raise RuntimeError("resume thread_id 与原运行 conversation_id 不一致")
        return run_row

    async def _finalize_resume_run(
        self,
        *,
        db: Session,
        conversation_id: str | None,
        context: AgentRuntimeContext,
        answer: str,
        elapsed_ms: float,
    ) -> None:
        """写入恢复后的用户可见历史会话，并把运行记录标记为成功。

        Args:
            db: PostgreSQL Session。
            conversation_id: 原运行绑定的业务会话 ID；为空时不写助手消息。
            context: 本次恢复使用的运行上下文。
            answer: Agent 恢复后的最终回答。
            elapsed_ms: 恢复阶段耗时，单位毫秒。
        """
        # 长期记忆当前仍是预留能力；真实的用户可见历史会话由 ContextService 写入 agent_messages。
        await self.memory_service.save_interaction(context, answer)

        assistant_message_id: str | None = None
        if conversation_id:
            assistant_message = self.context_service.add_assistant_message(
                db,
                conversation_id=context.thread_id,
                content=answer,
                metadata={"run_id": context.run_id, "resume": True},
            )
            assistant_message_id = assistant_message.message_id

        self.run_service.mark_success(
            db,
            run_id=context.run_id,
            answer=answer,
            assistant_message_id=assistant_message_id,
            elapsed_ms=elapsed_ms,
        )

    def _mark_resume_failed(self, db: Session, run_id: str, error: Exception, elapsed_ms: float) -> None:
        """把恢复失败写回 agent_runs。

        Args:
            db: PostgreSQL Session。
            run_id: 被恢复的运行 ID。
            error: 恢复执行异常。
            elapsed_ms: 恢复失败前耗时。
        """
        self.run_service.mark_failed(db, run_id=run_id, error_message=str(error), elapsed_ms=elapsed_ms)

    async def _finalize_resume_with_short_transaction(
        self,
        *,
        conversation_id: str | None,
        context: AgentRuntimeContext,
        answer: str,
        elapsed_ms: float,
    ) -> None:
        """使用独立短事务完成恢复成功落库。

        Args:
            conversation_id: 原运行绑定的业务会话 ID。
            context: 恢复运行上下文。
            answer: 恢复后的最终回答。
            elapsed_ms: 恢复阶段耗时。
        """
        with postgres_transaction() as final_db:
            await self._finalize_resume_run(
                db=final_db,
                conversation_id=conversation_id,
                context=context,
                answer=answer,
                elapsed_ms=elapsed_ms,
            )

    def _record_resume_failure(
        self,
        *,
        run_id: str,
        error: Exception,
        elapsed_ms: float,
    ) -> None:
        """使用独立短事务写入恢复失败状态。

        Args:
            run_id: 被恢复的运行 ID。
            error: 恢复执行异常。
            elapsed_ms: 恢复失败前耗时。
        """
        with postgres_transaction() as final_db:
            self._mark_resume_failed(final_db, run_id, error, elapsed_ms)

    async def resume(
        self,
        request: AgentResumeRequest,
    ) -> AgentRunResponse:
        """非流式恢复被中断的 Agent 运行。

        Args:
            request: 中断恢复请求。

        Returns:
            AgentRunResponse，包含原 run_id 和恢复后的最终回答。
        """
        run_started_at = time.perf_counter()
        context = None
        conversation_id: str | None = None
        try:
            # 恢复准备阶段只读取原运行快照并重新组装 Agent；退出 with 后，
            # LangGraph checkpoint 恢复和模型执行不会持有业务数据库 Session。
            with postgres_transaction() as start_db:
                run_row = self._get_interrupted_run(start_db, request)
                conversation_id = getattr(run_row, "conversation_id", None)
                resume_run_request = self._build_resume_request_from_run(run_row, request)
                context = self._build_resume_context(run_row, request, resume_run_request)

            # 原运行快照读取事务已关闭，重新组装和恢复执行不再持有业务 Session。
            assembly = await self.assembler.assemble(resume_run_request, context)

            if context is None:
                raise RuntimeError("Agent 恢复上下文初始化失败")
            result = await assembly.agent.ainvoke(
                Command(resume=request.resume_value),
                config={
                    "configurable": {"thread_id": context.thread_id},
                    "recursion_limit": get_agent_runtime_settings().recursion_limit,
                },
                context=context.to_langchain_context(),
            )
        except Exception as error:
            elapsed_ms = (time.perf_counter() - run_started_at) * 1000
            self._record_resume_failure(
                run_id=context.run_id if context is not None else request.run_id,
                error=error,
                elapsed_ms=elapsed_ms,
            )
            raise

        answer = self._extract_answer_from_result(result)
        elapsed_ms = (time.perf_counter() - run_started_at) * 1000
        await self._finalize_resume_with_short_transaction(
            conversation_id=conversation_id,
            context=context,
            answer=answer,
            elapsed_ms=elapsed_ms,
        )
        return AgentRunResponse(run_id=context.run_id, answer=answer)

    async def resume_stream(
        self,
        request: AgentResumeRequest,
    ) -> AsyncIterator[dict[str, Any]]:
        """流式恢复被中断的 Agent 运行。

        Args:
            request: 中断恢复请求。

        Yields:
            标准化 SSE 事件字典。
        """
        run_started_at = time.perf_counter()
        context = None
        conversation_id: str | None = None
        answer_parts: list[str] = []
        try:
            # 必须在发送第一个 SSE 事件前退出短事务，防止生成器暂停时占用连接。
            with postgres_transaction() as start_db:
                run_row = self._get_interrupted_run(start_db, request)
                conversation_id = getattr(run_row, "conversation_id", None)
                resume_run_request = self._build_resume_request_from_run(run_row, request)
                context = self._build_resume_context(run_row, request, resume_run_request)

            if context is None:
                raise RuntimeError("Agent 恢复上下文初始化失败")

            # 原运行快照读取事务已经关闭，可以立即把原 run_id 返回给客户端。
            yield {
                "type": "resume_start",
                "data": {
                    "run_id": context.run_id,
                    "thread_id": context.thread_id,
                    "stream": True,
                },
            }

            # 重新组装和恢复执行发生在开始事务关闭之后，不会持有业务 Session。
            assembly = await self.assembler.assemble(resume_run_request, context)
            yield {
                "type": "agent_assembled",
                "data": {
                    "run_id": context.run_id,
                    **assembly.metadata,
                },
            }

            suppress_sub_agent_messages = context.inputs.get("_stream_scope") != "sub_agent"
            interrupted_payload: dict[str, Any] | None = None
            last_task_plan_signature: str | None = None
            async for stream_chunk in assembly.agent.astream(
                Command(resume=request.resume_value),
                config={
                    "configurable": {"thread_id": context.thread_id},
                    "recursion_limit": get_agent_runtime_settings().recursion_limit,
                },
                context=context.to_langchain_context(),
                stream_mode=["messages", "updates", "custom"],
            ):
                stream_mode, chunk = stream_chunk if isinstance(stream_chunk, tuple) and len(stream_chunk) == 2 else ("messages", stream_chunk)

                if stream_mode == "messages":
                    for normalized_event in self.stream_parser.normalize_message_stream_chunk(
                        chunk,
                        suppress_sub_agent=suppress_sub_agent_messages,
                    ):
                        if normalized_event.get("type") == "model_delta":
                            content = (normalized_event.get("data") or {}).get("content")
                            if isinstance(content, str) and content:
                                answer_parts.append(content)
                        yield normalized_event
                    continue

                if stream_mode == "custom":
                    if isinstance(chunk, dict):
                        yield chunk
                    continue

                if stream_mode == "updates":
                    task_plan_event = self.stream_parser.extract_task_plan_event(chunk, context.run_id, context.thread_id)
                    if task_plan_event is not None:
                        task_plan = (task_plan_event.get("data") or {}).get("task_plan")
                        task_plan_signature = self.stream_parser.build_stable_signature(task_plan)
                        if task_plan_signature != last_task_plan_signature:
                            last_task_plan_signature = task_plan_signature
                            yield task_plan_event

                    interrupt_event = self.stream_parser.extract_interrupt_event(chunk, context.run_id, context.thread_id)
                    if interrupt_event is not None:
                        interrupted_payload = (interrupt_event.get("data") or {}).get("payload")
                        yield interrupt_event

            elapsed_ms = (time.perf_counter() - run_started_at) * 1000
            if interrupted_payload is not None:
                interrupt_type = str(interrupted_payload.get("type") or "unknown") if isinstance(interrupted_payload, dict) else "unknown"
                with postgres_transaction() as final_db:
                    self.run_service.mark_interrupted(
                        final_db,
                        run_id=context.run_id,
                        interrupt_type=interrupt_type,
                        interrupt_payload=interrupted_payload,
                        elapsed_ms=elapsed_ms,
                    )
                yield {
                    "type": "run_end",
                    "data": {
                        "run_id": context.run_id,
                        "thread_id": context.thread_id,
                        "status": "interrupted",
                        "interrupt_type": interrupt_type,
                        "elapsed_ms": elapsed_ms,
                        "answer_length": len("".join(answer_parts)),
                    },
                }
                return

            answer = "".join(answer_parts)
            await self._finalize_resume_with_short_transaction(
                conversation_id=conversation_id,
                context=context,
                answer=answer,
                elapsed_ms=elapsed_ms,
            )
            yield {
                "type": "run_end",
                "data": {
                    "run_id": context.run_id,
                    "thread_id": context.thread_id,
                    "status": "success",
                    "elapsed_ms": elapsed_ms,
                    "answer_length": len(answer),
                },
            }
        except Exception as error:
            elapsed_ms = (time.perf_counter() - run_started_at) * 1000
            logger.exception("Agent 恢复执行失败: run_id=%s thread_id=%s", request.run_id, request.thread_id)
            self._record_resume_failure(
                run_id=request.run_id,
                error=error,
                elapsed_ms=elapsed_ms,
            )
            yield {
                "type": "error",
                "data": {
                    "run_id": request.run_id,
                    "thread_id": request.thread_id,
                    "message": str(error),
                    "error_type": error.__class__.__name__,
                },
            }

    def _extract_answer_from_result(self, result: dict[str, Any]) -> str:
        """从 Agent 最终结果中提取最终文本回答。

        Args:
            result: Agent 执行最终结果。

        Returns:
            最终回答文本；不存在时返回空字符串。
        """
        messages = result.get("messages") or []
        if not messages:
            return ""

        last_message = messages[-1]
        if isinstance(last_message, dict):
            content = last_message.get("content", "")
        else:
            content = getattr(last_message, "content", "")

        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict) and item.get("type") in {"text", "output_text"}:
                    parts.append(str(item.get("text") or item.get("content") or ""))
            return "".join(parts)
        return str(content) if content is not None else ""
