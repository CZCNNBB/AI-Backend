import logging
from typing import Any

from langchain.agents.middleware import SummarizationMiddleware
from langchain_core.messages import AnyMessage, RemoveMessage
from langchain_core.messages.utils import get_buffer_string
from langgraph.config import get_stream_writer
from langgraph.graph.message import REMOVE_ALL_MESSAGES

from app.server.agent.src.config import get_agent_runtime_settings

logger = logging.getLogger("ai_backend.agent.context_summary")


CONVERSATION_SUMMARY_PROMPT = """你负责压缩 Agent 的早期会话上下文。

保留：
1. 用户目标、偏好、限制条件和已确认决定。
2. 已完成任务、关键结论、重要数据和生成的产物。
3. 尚未完成的任务、失败原因、待用户确认事项。
4. 工具调用得到的、后续仍需依赖的关键事实。

不要保留：
1. 无关寒暄和重复表述。
2. 已失效的中间推理细节。
3. 可以从当前近期消息直接获得的重复内容。

仅输出结构化上下文摘要，不要向用户说话。

<messages>
{messages}
</messages>
"""


class ConversationSummarizationMiddleware(SummarizationMiddleware):
    """平台会话上下文总结中间件。

    继承 LangChain 官方 SummarizationMiddleware，复用 Token 判断、近期消息保留和
    工具消息配对保护；平台扩展 SSE 状态事件、中文总结 Prompt 和失败降级行为。
    """

    def __init__(
        self,
        model: Any,
        trigger: tuple[str, int] | None = None,
        keep: tuple[str, int] | None = None,
        trim_tokens_to_summarize: int | None = None,
    ) -> None:
        """初始化会话总结中间件。

        Args:
            model: 本次 Agent 实际使用的聊天模型。
            trigger: 触发总结的 Token 阈值。
            keep: 总结后保留的近期消息数量。
            trim_tokens_to_summarize: 单次总结请求最多携带的 Token 数。
        """
        settings = get_agent_runtime_settings()
        effective_trigger = trigger or ("tokens", settings.context_summary_trigger_tokens)
        effective_keep = keep or ("messages", settings.context_summary_keep_messages)
        effective_trim_tokens = trim_tokens_to_summarize or settings.context_summary_trim_tokens

        # 总结调用使用同一模型配置，但增加标记，避免内部模型 Token 冒泡到用户 SSE。
        summary_model = model.with_config(
            tags=["nostream"],
            metadata={"lc_source": "summarization"},
        )
        super().__init__(
            model=summary_model,
            trigger=effective_trigger,
            keep=effective_keep,
            summary_prompt=CONVERSATION_SUMMARY_PROMPT,
            trim_tokens_to_summarize=effective_trim_tokens,
        )

    async def abefore_model(self, state: dict[str, Any], runtime: Any) -> dict[str, Any] | None:
        """在模型调用前按 Token 阈值压缩 Checkpointer 工作消息。

        发生总结时通过 LangGraph custom 流发送状态事件。总结失败只保留原状态，
        不能将异常文本写成摘要，也不能打断主 Agent 的正常执行。
        """
        messages = state.get("messages") or []
        self._ensure_message_ids(messages)
        total_tokens = self.token_counter(messages)
        if not self._should_summarize(messages, total_tokens):
            logger.debug("会话总结跳过: reason=threshold_not_reached tokens=%s", total_tokens)
            return None

        cutoff_index = self._determine_cutoff_index(messages)
        if cutoff_index <= 0:
            logger.debug("会话总结跳过: reason=no_safe_cutoff tokens=%s", total_tokens)
            return None

        messages_to_summarize, preserved_messages = self._partition_messages(messages, cutoff_index)
        run_id = self._get_run_id(runtime)
        self._emit_status_event("context_summary_started", run_id)
        logger.info(
            "会话总结开始: run_id=%s total_tokens=%s summarize_messages=%s preserved_messages=%s",
            run_id,
            total_tokens,
            len(messages_to_summarize),
            len(preserved_messages),
        )
        try:
            summary = await self._acreate_summary_safely(messages_to_summarize)
        except Exception:
            logger.exception("会话总结失败: run_id=%s total_tokens=%s", run_id, total_tokens)
            self._emit_status_event(
                "context_summary_failed",
                run_id,
                message="上下文总结失败，本轮将继续使用原始上下文。",
            )
            return None

        self._emit_status_event("context_summary_completed", run_id)
        logger.info(
            "会话总结完成: run_id=%s total_tokens=%s summary_length=%s",
            run_id,
            total_tokens,
            len(summary),
        )
        return {
            "messages": [
                RemoveMessage(id=REMOVE_ALL_MESSAGES),
                *self._build_new_messages(summary),
                *preserved_messages,
            ]
        }

    async def _acreate_summary_safely(self, messages_to_summarize: list[AnyMessage]) -> str:
        """调用总结模型并在异常时交由上层执行失败降级。

        LangChain 官方实现会把异常信息作为摘要文本返回；平台不接受这种行为，
        因此在此直接抛出异常，让调用方保持原始 Checkpointer 消息。
        """
        if not messages_to_summarize:
            return "没有需要保留的早期会话上下文。"

        trimmed_messages = self._trim_messages_for_summary(messages_to_summarize)
        if not trimmed_messages:
            return "早期会话内容过长，未能提取更多细节。"

        formatted_messages = get_buffer_string(trimmed_messages, format="xml")
        response = await self.model.ainvoke(
            self.summary_prompt.format(messages=formatted_messages).rstrip(),
            config={"metadata": {"lc_source": "summarization"}, "tags": ["nostream"]},
        )
        summary = str(getattr(response, "text", "") or "").strip()
        if not summary:
            raise RuntimeError("总结模型没有返回有效内容。")
        return summary

    def _get_run_id(self, runtime: Any) -> str:
        """从 LangGraph runtime context 中提取平台运行 ID。"""
        context = getattr(runtime, "context", None)
        if isinstance(context, dict):
            return str(context.get("run_id") or "")
        return str(getattr(context, "run_id", "") or "")

    def _emit_status_event(self, event_type: str, run_id: str, message: str | None = None) -> None:
        """通过 LangGraph custom 流发送会话总结状态，不携带摘要正文。"""
        try:
            writer = get_stream_writer()
        except RuntimeError:
            # 非流式运行不存在 custom writer；总结仍可正常完成。
            return

        data: dict[str, str] = {"run_id": run_id}
        if message:
            data["message"] = message
        writer({"type": event_type, "data": data})
