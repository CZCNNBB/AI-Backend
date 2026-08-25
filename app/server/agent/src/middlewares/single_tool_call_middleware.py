"""限制单轮模型响应最多保留一个工具调用。"""

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, SystemMessage
from langgraph.runtime import Runtime

logger = logging.getLogger(__name__)


class SingleToolCallMiddleware(AgentMiddleware[AgentState]):
    """裁剪模型并发工具调用，避免同一 LangGraph step 内多个工具同时写 state。"""

    def __init__(self, enabled: bool = True):
        """初始化单工具调用限制中间件。"""
        self.enabled = enabled

    def _inject_rule_prompt(self, request: ModelRequest) -> ModelRequest:
        """向系统提示词追加单工具顺序调用规则。"""
        rule_prompt = (
            "<single_tool_call_rule>\n"
            "工具调用规则：调用工具时必须一个一个调用。"
            "等待当前工具执行完成并看到工具结果后，再决定是否调用下一个工具。"
            "不要在同一轮模型响应中并行发起多个工具调用。\n"
            "</single_tool_call_rule>"
        )
        current_prompt = getattr(request.system_message, "content", "")
        new_system = SystemMessage(content=f"{current_prompt}\n\n{rule_prompt}")
        return request.override(system_message=new_system)

    def _clip_ai_message(self, message: AIMessage) -> AIMessage:
        """裁剪单条 AIMessage 中的并发工具调用，只保留第一个。"""
        tool_calls = getattr(message, "tool_calls", None) or []
        if len(tool_calls) <= 1:
            return message

        kept_tool_call = tool_calls[0]
        dropped_tool_calls = tool_calls[1:]
        logger.warning(
            "检测到模型单轮返回多个工具调用，已提前裁剪为只执行第一个工具: kept=%s, dropped=%s",
            kept_tool_call,
            dropped_tool_calls,
        )

        # 保持原消息 id 不变，让 LangGraph messages reducer 可以把裁剪后的消息视为同一条消息。
        clipped_msg = message.model_copy(update={"tool_calls": [kept_tool_call]})

        # 部分模型适配器会在 additional_kwargs 里保留原始 tool_calls，这里同步裁剪，
        # 避免 LangGraph tools 节点或前端流式解析读到未裁剪的原始数据。
        additional_kwargs = dict(getattr(clipped_msg, "additional_kwargs", {}) or {})
        if "tool_calls" in additional_kwargs:
            additional_kwargs["tool_calls"] = additional_kwargs["tool_calls"][:1]
            clipped_msg = clipped_msg.model_copy(update={"additional_kwargs": additional_kwargs})

        return clipped_msg

    def _clip_model_response(self, response: ModelResponse) -> ModelResponse:
        """在模型响应进入 LangGraph state 前裁剪并发工具调用。"""
        clipped_messages = list(response.result)
        for index in range(len(clipped_messages) - 1, -1, -1):
            message = clipped_messages[index]
            if not isinstance(message, AIMessage):
                continue

            clipped_message = self._clip_ai_message(message)
            if clipped_message is message:
                return response

            clipped_messages[index] = clipped_message
            return ModelResponse(
                result=clipped_messages,
                structured_response=response.structured_response,
            )

        return response

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        """同步模型调用前注入规则，并在模型响应进入 tools 节点前完成裁剪。"""
        if not self.enabled:
            return handler(request)

        response = handler(self._inject_rule_prompt(request))
        return self._clip_model_response(response)

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        """异步模型调用前注入规则，并在模型响应进入 tools 节点前完成裁剪。

        Args:
            request: LangChain 模型调用请求。
            handler: 后续模型调用处理器。

        Returns:
            模型调用结果。
        """
        if not self.enabled:
            return await handler(request)

        response = await handler(self._inject_rule_prompt(request))
        return self._clip_model_response(response)

    def _clip_tool_calls(self, state: AgentState) -> dict[str, Any] | None:
        """模型结束后的兜底裁剪，防止适配器绕过 wrap_model_call。"""
        if not self.enabled:
            return None

        messages = state.get("messages", [])
        if not messages:
            return None

        last_msg = messages[-1]
        if not isinstance(last_msg, AIMessage):
            return None

        clipped_msg = self._clip_ai_message(last_msg)
        if clipped_msg is last_msg:
            return None

        return {"messages": [clipped_msg]}

    def after_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        """同步模型调用结束后触发，用于兜底裁剪并发工具调用。"""
        return self._clip_tool_calls(state)

    async def aafter_model(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        """异步模型调用结束后触发，用于兜底裁剪并发工具调用。"""
        return self._clip_tool_calls(state)
