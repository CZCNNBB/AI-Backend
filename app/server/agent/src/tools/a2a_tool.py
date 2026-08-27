"""A2A 工具：把子 Agent 调用包装成 LangChain Tool。"""

import logging
import time
from uuid import uuid4

from langchain_core.tools import tool
from langgraph.config import get_stream_writer
from langgraph.prebuilt.tool_node import ToolRuntime

logger = logging.getLogger(__name__)


def _mark_agent_run_success(run_id: str, output_text: str, elapsed_ms: float) -> None:
    """把 A2A 子 Agent 运行记录标记为成功。

    Args:
        run_id: 子 Agent 本次运行 ID。
        output_text: 子 Agent 最终输出文本。
        elapsed_ms: 子 Agent 调用耗时，单位毫秒。
    """
    from app.common.db.postgres_db import postgres_transaction
    from app.server.agent.src.runs import AgentRunService

    # A2A 状态更新不经过 HTTP 依赖，必须显式建立短事务并在退出时提交。
    with postgres_transaction() as db:
        AgentRunService().mark_success(db, run_id=run_id, answer=output_text, elapsed_ms=elapsed_ms)


def _mark_agent_run_failed(run_id: str, error_message: str, elapsed_ms: float) -> None:
    """把 A2A 子 Agent 运行记录标记为失败。

    Args:
        run_id: 子 Agent 本次运行 ID。
        error_message: 子 Agent 调用失败原因。
        elapsed_ms: 子 Agent 调用失败前耗时，单位毫秒。
    """
    from app.common.db.postgres_db import postgres_transaction
    from app.server.agent.src.runs import AgentRunService

    # 失败状态单独落库，避免子 Agent 异常导致运行记录永久停留在 running。
    with postgres_transaction() as db:
        AgentRunService().mark_failed(db, run_id=run_id, error_message=error_message, elapsed_ms=elapsed_ms)


@tool("a2a_call")
async def a2a_call(agent_id: str, query: str, runtime: ToolRuntime) -> str:
    """调用子 Agent 执行子任务。

    这个工具会在内部流式运行子 Agent，并把子 Agent 过程包装为 sub_agent_event 写入 custom 流。
    子 Agent 返回完整文本后，主 Agent 再把结果整合进最终回答。

    安全边界：
    1. 目标 Agent 模板必须存在且声明 is_sub_agent=true。
    2. 子 Agent 调用时不传 conversation_id，不落 LangGraph checkpoint。
    3. 子 Agent 调用时 long_term_memory_enabled=False，避免读写用户长期记忆。
    4. 子 Agent 调用时 a2a=None，不递归调用。
    5. 模型通过 system prompt 中的 <a2a_instruct> 获知可用子 Agent 列表。

    Args:
        agent_id: 要调用的子 Agent 模板 ID。
        query: 传给子 Agent 的完整任务说明。
        runtime: LangGraph 注入的工具运行时，用于读取父级上下文和 tool_call_id。

    Returns:
        子 Agent 的最终文本回答；校验失败或调用失败时返回错误说明文本。
    """
    from app.common.db.postgres_db import postgres_transaction
    from app.server.agent.src.agent.service import AgentService
    from app.server.agent.src.runs import AgentRunService
    from app.server.agent.src.schemas.request import AgentKnowledgeConfig, AgentRunRequest
    from app.server.agent.src.templates.service import AgentTemplateService

    parent_conversation_id = None
    parent_run_id = None
    parent_inputs: dict = {}
    parent_knowledge_base_ids: list[str] = []
    parent_platform_id: int | None = None
    parent_external_user_id: str | None = None
    parent_runtime_credentials: dict[str, str] = {}
    parent_tool_call_id = getattr(runtime, "tool_call_id", None) if runtime is not None else None
    if runtime is not None:
        ctx = getattr(runtime, "context", None) or {}
        if isinstance(ctx, dict):
            parent_conversation_id = str(ctx.get("thread_id") or "") or None
            parent_run_id = str(ctx.get("run_id") or "") or None
            parent_inputs = dict(ctx.get("inputs") or {})
            parent_knowledge_base_ids = list(ctx.get("knowledge_base_ids") or [])
            parent_platform_id = ctx.get("platform_id")
            parent_external_user_id = str(ctx.get("external_user_id") or "") or None
            parent_runtime_credentials = dict(ctx.get("runtime_credentials") or {})
        elif hasattr(ctx, "model_dump"):
            context_data = ctx.model_dump()
            parent_conversation_id = str(context_data.get("thread_id") or "") or None
            parent_run_id = str(context_data.get("run_id") or "") or None
            parent_inputs = dict(context_data.get("inputs") or {})
            parent_knowledge_base_ids = list(context_data.get("knowledge_base_ids") or [])
            parent_platform_id = context_data.get("platform_id")
            parent_external_user_id = str(context_data.get("external_user_id") or "") or None
            parent_runtime_credentials = dict(context_data.get("runtime_credentials") or {})

    if parent_platform_id is None or not parent_external_user_id:
        return "错误：A2A 调用缺少业务平台或外部用户身份。"

    sub_run_id = uuid4().hex
    sub_started_at = time.perf_counter()

    # 校验：模板必须存在，并且明确声明自己可以作为子 Agent 被调用。
    # 校验通过后立即写入 agent_runs(run_type=sub)，保证后续模型调用失败也能追踪到这次子任务。
    # 模板校验和子运行记录创建属于一个短事务；模型执行发生在事务关闭之后。
    with postgres_transaction() as db:
        template_service = AgentTemplateService()
        template_view = template_service.get_template(db, agent_id)
        if template_view is None:
            return f"错误：子 Agent {agent_id} 的模板不存在或已被删除。"

        config = template_view.config
        if not config.is_sub_agent:
            return f"错误：Agent {agent_id} 未声明为可被 A2A 调用的子 Agent。"

        # 子 Agent 必须同样分配给当前业务平台，避免主 Agent 绕过入口绑定调用其他平台 Agent。
        from app.server.platform.src.service import BusinessPlatformService

        BusinessPlatformService().require_agent_binding(
            db,
            agent_id=agent_id,
            platform_id=parent_platform_id,
        )

        AgentRunService().create_running(
            db,
            run_id=sub_run_id,
            platform_id=parent_platform_id,
            external_user_id=parent_external_user_id,
            run_type="sub",
            parent_run_id=parent_run_id,
            agent_id=agent_id,
            conversation_id=parent_conversation_id,
            query=query,
            metadata={"source": "a2a_call"},
        )

    # 子 Agent 不传 conversation_id，因此 AgentAssembler 不会挂 PostgreSQL checkpointer。
    # A2A 子 Agent 不写 agent_conversations/agent_messages，也不额外创建主运行记录。
    from app.server.agent.src.schemas.request import AgentRuntimeCredentials

    sub_request = AgentRunRequest(
        platform_id=parent_platform_id,
        external_user_id=parent_external_user_id,
        runtime_credentials=AgentRuntimeCredentials(**parent_runtime_credentials),
        query=query,
        conversation_id=None,
        system_prompt=config.system_prompt,
        inputs={
            # 可信业务 inputs 必须传递给子 Agent，供 ToolArgsInjectMiddleware 注入 MCP 工具参数。
            **parent_inputs,
            "_stream_scope": "sub_agent",
            "_sub_run_id": sub_run_id,
            "_sub_agent_id": agent_id,
            "_parent_run_id": parent_run_id,
            "_parent_conversation_id": parent_conversation_id,
        },
        tools=list(config.tools or []),
        # 子 Agent 继承模板能力，但强制关闭长期记忆，保持本次 A2A 调用无状态。
        optional_features=config.optional_features.model_copy(
            update={"long_term_memory_enabled": False},
            deep=True,
        ),
        # 子 Agent 只能继承父运行已经授权的知识库范围，不能自行扩大访问边界。
        knowledge=(
            AgentKnowledgeConfig(knowledge_base_ids=parent_knowledge_base_ids)
            if parent_knowledge_base_ids
            else None
        ),
        runtime_options=config.runtime_options,
        a2a=None,
    )

    sub_service = AgentService()
    try:
        writer = get_stream_writer()
    except RuntimeError:
        # 非流式调用时可能不存在 LangGraph custom stream writer，此时只返回最终工具结果。
        writer = lambda _: None
    answer_parts: list[str] = []

    def write_sub_agent_event(event: dict) -> None:
        """把子 Agent 标准事件包装成 sub_agent_event 并写入 custom 流。

        Args:
            event: 子 Agent 内部 stream() 产出的标准事件。
        """
        writer({
            "type": "sub_agent_event",
            "data": {
                "parent_run_id": parent_run_id,
                "parent_conversation_id": parent_conversation_id,
                "parent_tool_call_id": parent_tool_call_id,
                "sub_run_id": sub_run_id,
                "agent_id": agent_id,
                "event": event,
            },
        })

    try:
        # A2A 子运行的台账已经由本工具单独创建和更新，子 AgentService 不再重复写主运行记录。
        async for event in sub_service.stream(
            sub_request,
            persist_business_records=False,
        ):
            # 子 Agent 自己产出的标准事件统一包成 sub_agent_event 交给前端。
            write_sub_agent_event(event)
            if event.get("type") == "model_delta":
                content = (event.get("data") or {}).get("content")
                if isinstance(content, str) and content:
                    answer_parts.append(content)

        answer = "".join(answer_parts)
        elapsed_ms = (time.perf_counter() - sub_started_at) * 1000
        _mark_agent_run_success(sub_run_id, answer, elapsed_ms)
        return answer
    except Exception as error:
        elapsed_ms = (time.perf_counter() - sub_started_at) * 1000
        logger.exception("A2A sub-agent call failed: agent_id=%s sub_run_id=%s", agent_id, sub_run_id)
        _mark_agent_run_failed(sub_run_id, str(error), elapsed_ms)
        error_message = f"子 Agent 调用失败：{error}"
        write_sub_agent_event({
            "type": "run_end",
            "data": {
                "run_id": sub_run_id,
                "status": "failed",
                "message": error_message,
                "elapsed_ms": elapsed_ms,
            },
        })
        return error_message
