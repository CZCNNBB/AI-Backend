import logging
import time
from typing import Any, AsyncIterator

from langgraph.errors import GraphInterrupt
from sqlmodel import Session

from app.server.agent.src.agent.assembler import AgentAssembler
from app.server.agent.src.checkpoint import AgentCheckpointService
from app.server.agent.src.context import AgentContextService
from app.server.agent.src.memory import AgentMemoryService
from app.server.agent.src.middlewares import MiddlewareFactory
from app.server.agent.src.model import AgentModelService
from app.server.agent.src.prompts import AgentPromptService
from app.server.agent.src.runtime import AgentRuntimeContextService
from app.server.agent.src.runs import AgentRunService
from app.server.agent.src.schemas.request import AgentResumeRequest, AgentRunRequest
from app.server.agent.src.agent.tool_results import collect_tool_results
from app.server.agent.src.schemas.response import AgentRunResponse
from app.server.agent.src.config import get_agent_runtime_settings
from app.server.agent.src.templates.service import AgentTemplateService
from app.server.agent.src.agent.run_lifecycle import AgentRunLifecycleService
from app.server.agent.src.tools import AgentToolService
from app.server.agent.src.agent.resume_service import AgentResumeService
from app.server.agent.src.agent.streaming import AgentStreamEventParser


logger = logging.getLogger("ai_backend.agent")


class AgentService:
    """平台通用 Agent 服务，负责运行上下文管理、会话持久化和执行调度。

    Agent 组装流程已提取到 AgentAssembler，运行生命周期已提取到 AgentRunLifecycleService。
    本层只关心同步 / 流式执行调度。
    """

    def __init__(
        self,
        *,
        assembler: AgentAssembler | None = None,
        model_service: AgentModelService | None = None,
        tool_service: AgentToolService | None = None,
        prompt_service: AgentPromptService | None = None,
        runtime_context_service: AgentRuntimeContextService | None = None,
        middleware_factory: MiddlewareFactory | None = None,
        memory_service: AgentMemoryService | None = None,
        checkpoint_service: AgentCheckpointService | None = None,
        context_service: AgentContextService | None = None,
        run_service: AgentRunService | None = None,
        template_service: AgentTemplateService | None = None,
        stream_parser: AgentStreamEventParser | None = None,
    ):
        """初始化平台通用 Agent 服务。

        Args:
            assembler: Agent 组装器，不传时自动创建。
            model_service: 模型服务（仅在未传 assembler 时用于构建默认组装器）。
            tool_service: 工具服务（同上）。
            prompt_service: Prompt 服务（同上）。
            runtime_context_service: 运行时上下文服务，负责构建 thread_id、inputs 等。
            middleware_factory: 中间件工厂（同上）。
            memory_service: 长期记忆预留服务，当前不负责用户可见历史会话。
            checkpoint_service: Checkpointer 服务（同上）。
            context_service: 历史会话服务，负责读写 agent_conversations 和 agent_messages。
            run_service: Agent 主运行记录服务，负责读写 agent_runs。
            template_service: Agent 模板服务，负责按 agent_id 加载模板配置。
            stream_parser: 流式消息解析器，负责把 LangGraph messages/updates 分片转成 SSE 事件。
        """
        self.assembler = assembler or AgentAssembler(
            model_service=model_service or AgentModelService(),
            tool_service=tool_service or AgentToolService(),
            prompt_service=prompt_service or AgentPromptService(),
            runtime_context_service=runtime_context_service or AgentRuntimeContextService(),
            middleware_factory=middleware_factory or MiddlewareFactory(),
            checkpoint_service=checkpoint_service or AgentCheckpointService(),
        )
        self.runtime_context_service = runtime_context_service or AgentRuntimeContextService()
        self.memory_service = memory_service or AgentMemoryService()
        self.context_service = context_service or AgentContextService()
        self.run_service = run_service or AgentRunService()
        self.template_service = template_service or AgentTemplateService()
        self.stream_parser = stream_parser or AgentStreamEventParser()
        self.lifecycle_service = AgentRunLifecycleService(
            runtime_context_service=self.runtime_context_service,
            memory_service=self.memory_service,
            context_service=self.context_service,
            run_service=self.run_service,
            template_service=self.template_service,
        )
        self.resume_service = AgentResumeService(
            assembler=self.assembler,
            memory_service=self.memory_service,
            context_service=self.context_service,
            run_service=self.run_service,
            stream_parser=self.stream_parser,
        )

        # 向后兼容：API 层通过 agent_service.tool_service 访问工具列表。
        self.tool_service = self.assembler.tool_service


    # ── 同步执行 ────────────────────────────────────────────────

    async def run(self, request: AgentRunRequest, db: Session | None = None) -> AgentRunResponse:
        """运行通用 Agent（非流式）。

        Args:
            request: 通用 Agent 运行请求。
            db: PostgreSQL Session。API 调用场景会传入；A2A 子 Agent 会传 None，避免写入主运行表。

        Returns:
            AgentRunResponse，包含本次 run_id、最终回答和结构化输出。
        """
        run_started_at = time.perf_counter()

        # 第一步：如果传入 agent_id，先加载模板并合并本次运行覆盖配置。
        request = self.lifecycle_service.resolve_template_request(request, db)

        # 第二步：构建运行上下文、写入用户消息，并创建 agent_runs 主运行记录。
        # 附件解析与注入交给 FileContextMiddleware 处理，避免 AgentService 堆积业务能力。
        context, context_enabled, run_record_enabled = self.lifecycle_service.prepare_run_context(request, db)

        try:
            # 第三步：组装 Agent。这里会加载模型、工具、中间件和 checkpointer。
            assembly = await self.assembler.assemble(request, context, db)
        except Exception as error:
            elapsed_ms = (time.perf_counter() - run_started_at) * 1000
            logger.exception(
                "Agent 组装失败: run_id=%s thread_id=%s elapsed_ms=%.2f",
                context.run_id,
                context.thread_id,
                elapsed_ms,
            )
            self.lifecycle_service.mark_run_failed(context, run_record_enabled, db, error, elapsed_ms)
            raise

        # 第三步：只传入本轮用户消息；跨轮 Agent 记忆由 checkpointer 根据 thread_id 恢复。
        # 附件内容由 FileContextMiddleware 注入 system prompt，不改写用户原始 query。
        input_messages = [{"role": "user", "content": request.query}]
        logger.info("Agent 执行开始: run_id=%s thread_id=%s", context.run_id, context.thread_id)
        try:
            result = await assembly.agent.ainvoke(
                {"messages": input_messages},
                config=self._build_langgraph_config(context),
                context=context.to_langchain_context(),
            )
        except GraphInterrupt:
            # GraphInterrupt 是 LangGraph 正常的人机交互中断机制，不是错误。
            # 非流式路径下 ainvoke 不会内部捕获它，需要在这里兜底处理。
            elapsed_ms = (time.perf_counter() - run_started_at) * 1000
            if run_record_enabled and db is not None:
                self.run_service.mark_interrupted(
                    db,
                    run_id=context.run_id,
                    interrupt_type="unknown",
                    interrupt_payload=None,
                    elapsed_ms=elapsed_ms,
                )
            # 重新抛出，让 API 层感知到中断并返回给前端。
            raise
        except Exception as error:
            elapsed_ms = (time.perf_counter() - run_started_at) * 1000
            logger.exception(
                "Agent 执行失败: run_id=%s thread_id=%s elapsed_ms=%.2f",
                context.run_id,
                context.thread_id,
                elapsed_ms,
            )
            self.lifecycle_service.mark_run_failed(context, run_record_enabled, db, error, elapsed_ms)
            if context_enabled:
                self.context_service.add_error(
                    db,
                    conversation_id=context.thread_id,
                    error_message=f"模型服务出错：{error}",
                    metadata={"run_id": context.run_id},
                )
            raise

        # 第四步：提取最终回答和结构化输出。
        # 兼容普通字符串以及 [{"type": "text", "text": "..."}] 内容块。
        answer = self._extract_answer_from_result(result)

        # AIMessage.tool_calls 记录模型实际发出的工具调用。
        # 统计该值可以区分“工具已装配但模型未选择调用”和“工具执行阶段发生异常”。
        tool_call_names: list[str] = []
        for message in result.get("messages") or []:
            for tool_call in getattr(message, "tool_calls", None) or []:
                tool_name = tool_call.get("name")
                if tool_name:
                    tool_call_names.append(str(tool_name))

        elapsed_ms = (time.perf_counter() - run_started_at) * 1000
        logger.info(
            "Agent 执行完成: run_id=%s thread_id=%s answer_length=%d "
            "tool_call_count=%d tool_calls=%s elapsed_ms=%.2f",
            context.run_id,
            context.thread_id,
            len(answer) if isinstance(answer, str) else 0,
            len(tool_call_names),
            tool_call_names,
            elapsed_ms,
        )

        # 第五步：写入用户可见历史会话，并把 agent_runs 标记为 success。
        await self.lifecycle_service.finalize_run(
            context,
            answer,
            context_enabled,
            run_record_enabled,
            db,
            elapsed_ms,
        )

        logger.info(
            "Agent 运行结束: run_id=%s thread_id=%s context_saved=%s total_elapsed_ms=%.2f",
            context.run_id,
            context.thread_id,
            context_enabled,
            elapsed_ms,
        )

        return AgentRunResponse(
            run_id=context.run_id,
            answer=answer,
            # 这里只返回已经产生 ToolMessage 的真实执行结果，模型声明的 tool_calls 不算成功。
            tool_results=collect_tool_results(list(result.get("messages") or [])),
        )

    def _build_langgraph_config(self, context) -> dict[str, Any]:
        """构建 LangGraph 调用配置，并注入用于流式诊断的 metadata。

        Args:
            context: 当前 Agent 运行上下文。

        Returns:
            可传给 agent.ainvoke / agent.astream 的 LangGraph config。
        """
        metadata: dict[str, Any] = {
            "agent_run_id": context.run_id,
            "agent_thread_id": context.thread_id,
        }
        # A2A 子 Agent 会通过 inputs 写入这些诊断字段，用于观察子 Agent 的运行情况。
        # 原始流式分片冒泡到主 Agent 时，metadata 是否仍能保留子运行身份。
        for key in [
            "_stream_scope",
            "_sub_run_id",
            "_sub_agent_id",
            "_parent_run_id",
            "_parent_conversation_id",
        ]:
            value = context.inputs.get(key) if isinstance(context.inputs, dict) else None
            if value is not None:
                metadata[key] = value

        return {
            "configurable": {"thread_id": context.thread_id},
            "recursion_limit": get_agent_runtime_settings().recursion_limit,
            "metadata": metadata,
        }

    # ── 流式执行 ────────────────────────────────────────────────
    async def stream(self, request: AgentRunRequest, db: Session | None = None) -> AsyncIterator[dict[str, Any]]:
        """流式运行通用 Agent，并产出可转换为 SSE 的事件。

        Args:
            request: 通用 Agent 运行请求；stream=true 时由 API 层调用本方法。
            db: PostgreSQL Session，用于写入 agent_runs 和用户可见会话记录。

        Yields:
            标准化事件字典，包含 type、data 等字段；API 层负责序列化为 SSE。
        """
        run_started_at = time.perf_counter()

        # 第一步：如果传入 agent_id，先加载模板并合并本次运行覆盖配置。
        request = self.lifecycle_service.resolve_template_request(request, db)

        # 第二步：构建运行上下文、写入用户消息，并创建 agent_runs 主运行记录。
        # 附件解析与注入交给 FileContextMiddleware 处理，避免 AgentService 堆积业务能力。
        context, context_enabled, run_record_enabled = self.lifecycle_service.prepare_run_context(request, db)
        yield {
            "type": "run_start",
            "data": {
                "run_id": context.run_id,
                "thread_id": context.thread_id,
                "persistent_conversation": request.conversation_id is not None,
                "stream": True,
            },
        }

        try:
            # 第三步：组装 Agent。这里会加载模型、工具、中间件和 checkpointer。
            assembly = await self.assembler.assemble(request, context, db)
            yield {
                "type": "agent_assembled",
                "data": {
                    "run_id": context.run_id,
                    **assembly.metadata,
                },
            }

            # 第三步：只传入本轮用户消息；跨轮 Agent 记忆由 checkpointer 根据 thread_id 恢复。
            # 附件内容由 FileContextMiddleware 注入 system prompt，不改写用户原始 query。
            input_messages = [{"role": "user", "content": request.query}]
            invoke_config = self._build_langgraph_config(context)
            answer_parts: list[str] = []
            suppress_sub_agent_messages = context.inputs.get("_stream_scope") != "sub_agent"

            # 第四步：同时消费 messages、updates 和 custom 流。
            # - messages：模型 token、reasoning、工具调用等前端实时内容。
            # - updates：LangGraph interrupt 只会在 updates 中出现，单独使用 messages 会丢失中断事件。
            # 流式模式下前端已经实时收到了 model_delta，因此接口末尾不再额外发送 final 事件；
            # 这里仅在后端累计正文 token，用于写入 agent_messages / agent_runs。
            interrupted_payload: dict[str, Any] | None = None
            last_task_plan_signature: str | None = None
            async for stream_chunk in assembly.agent.astream(
                {"messages": input_messages},
                config=invoke_config,
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
                    task_plan_event = self.stream_parser.extract_task_plan_event(
                        chunk,
                        context.run_id,
                        context.thread_id,
                    )
                    if task_plan_event is not None:
                        task_plan = (task_plan_event.get("data") or {}).get("task_plan")
                        task_plan_signature = self.stream_parser.build_stable_signature(task_plan)
                        if task_plan_signature != last_task_plan_signature:
                            last_task_plan_signature = task_plan_signature
                            yield task_plan_event

                    interrupt_event = self.stream_parser.extract_interrupt_event(
                        chunk,
                        context.run_id,
                        context.thread_id,
                    )
                    if interrupt_event is not None:
                        interrupted_payload = (interrupt_event.get("data") or {}).get("payload")
                        yield interrupt_event

            elapsed_ms = (time.perf_counter() - run_started_at) * 1000
            if interrupted_payload is not None:
                interrupt_type = str(interrupted_payload.get("type") or "unknown") if isinstance(interrupted_payload, dict) else "unknown"
                if run_record_enabled and db is not None:
                    self.run_service.mark_interrupted(
                        db,
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

            # 第五步：流式 token 已经全部推送完成，使用累计正文作为最终回答。
            # 这里不能调用 aget_state()，因为无状态运行不会挂 checkpointer，调用会触发 No checkpointer set。
            answer = "".join(answer_parts)
            await self.lifecycle_service.finalize_run(
                context,
                answer,
                context_enabled,
                run_record_enabled,
                db,
                elapsed_ms,
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
        except GraphInterrupt as error:
            # astream 在部分 LangGraph 版本中可能不会内部捕获 middleware before_model
            # 中触发的 GraphInterrupt，这里作为兜底安全网：把它当作正常中断而非错误。
            elapsed_ms = (time.perf_counter() - run_started_at) * 1000
            interrupt_event = self.stream_parser.extract_interrupt_event_from_error(
                error,
                context.run_id,
                context.thread_id,
            )
            if interrupt_event is not None:
                interrupted_payload = (interrupt_event.get("data") or {}).get("payload")
                yield interrupt_event
                # 兜底提取 task_plan（astream updates 路径没走到时，这里补发）。
                task_plan_event = self.stream_parser.extract_task_plan_event_from_interrupt(
                    interrupt_event,
                    context.run_id,
                    context.thread_id,
                )
                if task_plan_event is not None:
                    yield task_plan_event
            else:
                interrupted_payload = None

            interrupt_type = str(interrupted_payload.get("type") or "unknown") if isinstance(interrupted_payload, dict) else "unknown"
            if run_record_enabled and db is not None:
                self.run_service.mark_interrupted(
                    db,
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
        except Exception as error:
            elapsed_ms = (time.perf_counter() - run_started_at) * 1000
            logger.exception(
                "Agent 流式执行失败: run_id=%s thread_id=%s elapsed_ms=%.2f",
                context.run_id,
                context.thread_id,
                elapsed_ms,
            )
            self.lifecycle_service.mark_run_failed(context, run_record_enabled, db, error, elapsed_ms)
            if context_enabled:
                self.context_service.add_error(
                    db,
                    conversation_id=context.thread_id,
                    error_message=f"模型服务出错：{error}",
                    metadata={"run_id": context.run_id},
                )
            yield {
                "type": "error",
                "data": {
                    "run_id": context.run_id,
                    "message": str(error),
                    "error_type": error.__class__.__name__,
                },
            }

    # ── 中断恢复 ────────────────────────────────────────────────

    async def resume(self, request: AgentResumeRequest, db: Session | None = None) -> AgentRunResponse:
        """恢复被中断的 Agent 运行（非流式）。

        Args:
            request: 中断恢复请求。
            db: PostgreSQL Session。

        Returns:
            AgentRunResponse，包含原 run_id 和最终回答。
        """
        return await self.resume_service.resume(request, db)

    async def resume_stream(self, request: AgentResumeRequest, db: Session | None = None) -> AsyncIterator[dict[str, Any]]:
        """恢复被中断的 Agent 运行（流式）。

        Args:
            request: 中断恢复请求。
            db: PostgreSQL Session。

        Yields:
            标准化 SSE 事件字典。
        """
        async for event in self.resume_service.resume_stream(request, db):
            yield event

    # ── 结果提取 ────────────────────────────────────────────────

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
        # final_result.values 经过 safe_event_value 后，LangChain 消息对象会变成 dict；
        # 非流式路径里仍可能是原始消息对象，所以这里两种形态都要兼容。
        if isinstance(last_message, dict):
            content = last_message.get("content", "")
        else:
            content = getattr(last_message, "content", "")

        if isinstance(content, str):
            return content
        if isinstance(content, list):
            # 兼容多模态 / reasoning block 形态，只抽取可展示文本。
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict) and item.get("type") in {"text", "output_text"}:
                    parts.append(str(item.get("text") or item.get("content") or ""))
            return "".join(parts)
        return str(content) if content is not None else ""
